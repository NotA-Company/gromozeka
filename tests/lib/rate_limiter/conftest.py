"""Shared test helpers for the rate_limiter test suite.

Provides a controllable fake clock that eliminates real time-blocking from
rate limiter tests. The production SlidingWindowRateLimiter blocks inside
``applyLimit`` via ``await asyncio.sleep(waitTime)`` and reads the wall clock
via ``time.time()``; this helper patches both so tests fast-forward time
instead of waiting for real windows to elapse.

Because every test in this directory is a ``unittest.IsolatedAsyncioTestCase``
subclass (where pytest fixture argument injection is unreliable), the clock is
exposed as a plain helper called from each class's ``asyncSetUp`` rather than
as a pytest fixture.
"""

import asyncio
import unittest
from typing import List
from unittest.mock import patch


def installFakeClock(testCase: unittest.TestCase) -> List[float]:
    """Install a fake clock on a unittest TestCase for the test's duration.

    Patches ``time.time``, ``time.sleep``, and ``asyncio.sleep`` so that:
    - ``time.time()`` returns a mutable fake "now" (starting at 0.0),
    - sleeping (sync or async) advances the fake clock instead of blocking,
    - concurrent ``asyncio.sleep`` calls overlap (wall-clock semantics) by
      advancing "now" to the maximum sleep deadline rather than summing waits.

    The base is 0.0 (not real time) so window comparisons such as
    ``currentTime - reqTime < windowSeconds`` stay free of float-precision
    drift that would otherwise leave stale entries at exact window boundaries.

    Patchers are registered on ``testCase.addCleanup`` so they are torn down
    automatically after each test.

    Args:
        testCase: The unittest TestCase instance installing the clock. Used
            only to register cleanup of the patchers.

    Returns:
        A one-element mutable list ``[now]``. Tests may advance the clock
        directly via ``result[0] += seconds`` to simulate time passing.
    """
    realAsyncSleep = asyncio.sleep
    now: List[float] = [0.0]

    def fakeTime() -> float:
        """Return the current fake time.

        Returns:
            The current value of the fake clock.
        """
        return now[0]

    def fakeTimeSleep(seconds: float) -> None:
        """Advance the fake clock by ``seconds`` (sync sleep stand-in).

        Args:
            seconds: Number of fake seconds to advance.
        """
        now[0] += seconds

    async def fakeAsyncSleep(seconds: float) -> None:
        """Advance the fake clock by ``seconds`` without blocking.

        Uses a max-deadline update so concurrent sleeps started at the same
        instant overlap (mirroring real wall-clock behaviour) instead of
        stacking additively. Yields once via the real event loop to keep
        cooperative scheduling healthy under ``asyncio.gather``.

        Args:
            seconds: How many fake seconds the caller requested.
        """
        deadline = now[0] + seconds
        await realAsyncSleep(0)
        now[0] = max(now[0], deadline)

    patchers = (
        patch("time.time", fakeTime),
        patch("time.sleep", fakeTimeSleep),
        patch("asyncio.sleep", fakeAsyncSleep),
    )
    for patcher in patchers:
        patcher.start()
        testCase.addCleanup(patcher.stop)
    return now
