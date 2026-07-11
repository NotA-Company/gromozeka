"""Shared fixtures and helpers for ``lib/cache`` tests.

Provides a controllable fake clock so TTL/expiry assertions run without real
wall-clock waiting. Instead of sleeping, tests advance the fake clock directly
(``fakeClock[0] += N`` or ``fakeNow[0] += N``).

Note:
    The cache under test (``lib.cache.dict_cache.DictCache``) reads wall-clock
    time via the global ``time.time()`` call, so patching the ``time`` module
    functions is sufficient to control TTL/expiry behaviour deterministically.
"""

import time as _timeModule
from contextlib import contextmanager
from typing import Iterator, List
from unittest.mock import patch

import pytest


@contextmanager
def fakeClockContext() -> Iterator[List[float]]:
    """Patch ``time.time``/``time.sleep`` with a controllable fake clock.

    Replaces the global ``time.time`` with a mutable value and ``time.sleep``
    with an instant forward-jump of the fake clock. Intended for unittest-style
    tests (``test_integration.py``) that cannot receive pytest fixture
    arguments. Patches are restored automatically on context exit.

    Yields:
        List[float]: one-element list ``[now]`` in epoch seconds; mutate
            ``now[0]`` to advance the clock.
    """
    now: List[float] = [_timeModule.time()]

    def fakeTime() -> float:
        """Return the current fake clock value.

        Returns:
            float: Current fake time in epoch seconds.
        """
        return now[0]

    def fakeSleep(seconds: float) -> None:
        """Advance the fake clock by ``seconds`` instead of really sleeping.

        Args:
            seconds: Amount to add to the fake clock.
        """
        now[0] = now[0] + seconds

    with patch("time.time", new=fakeTime), patch("time.sleep", new=fakeSleep):
        yield now


@pytest.fixture
def fakeClock() -> Iterator[List[float]]:
    """Controllable fake clock so TTL/expiry assertions run without real waiting.

    Patches the global ``time.time`` with a mutable value and ``time.sleep``
    with an instant forward-jump of the fake clock. Advance the clock manually
    (e.g. ``fakeClock[0] += 2.1``) in place of ``await asyncio.sleep(2.1)``.

    Yields:
        List[float]: one-element list ``[now]`` in epoch seconds; mutate
            ``now[0]`` to advance the clock.
    """
    with fakeClockContext() as now:
        yield now
