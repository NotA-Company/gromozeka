"""Unit tests for ``SpamHandler._getUserInfoFreshIfMessagesLessThan``.

Covers the conditional-refresh micro-optimisation introduced alongside the
write-through ``chat_users`` cache (ADR-015). The helper reads the cached
``userInfo`` and re-fetches from DB ONLY when the cached ``messages_count`` is
strictly less than the supplied threshold. Rationale: ``messages_count`` is
monotonically non-decreasing (incremented by a raw SQL UPDATE in
``ChatMessagesRepository.saveChatMessage`` that bypasses the cache), so a cached
value at or above the threshold can only stay there or grow and remains valid
for any ``>=`` / ``>`` gate.

The helper is a pure consumer of ``self.cache.getChatUser`` — it touches nothing
else on the handler — so ``SpamHandler`` is instantiated via ``__new__``
(bypassing the heavy ``__init__`` that wires the Bayes filter, ConfigManager,
Database, and bot provider) and a mock ``cache`` is attached directly. This
isolates the refresh logic and lets us assert the exact
``getChatUser(refresh=True)`` call count.

Threshold values mirror the real production call sites in
``internal/bot/common/handlers/spam.py``:

* ``checkSpam`` uses a ``>=`` gate and passes ``maxCheckMessages`` unchanged.
* ``markAsSpam`` uses a STRICT ``>`` gate and passes ``maxSpamMessages + 1`` so
  the boundary case (``cached == maxSpamMessages``) still triggers a refresh.
"""

from typing import Optional, Tuple
from unittest.mock import AsyncMock

from internal.bot.common.handlers.spam import SpamHandler
from internal.database.models import ChatUserDict
from lib import utils


def _makeRow(*, messagesCount: int, chatId: int = 1, userId: int = 2) -> ChatUserDict:
    """Build a minimal ``ChatUserDict`` with the given ``messages_count``.

    Args:
        messagesCount: Value for the ``messages_count`` field (the only field
            the helper branches on).
        chatId: Chat id (default 1).
        userId: User id (default 2).

    Returns:
        A fully-populated ``ChatUserDict`` (non-null fields filled with
        sentinels) suitable for ``cache.getChatUser`` to return.
    """
    now = utils.now()
    return ChatUserDict(
        chat_id=chatId,
        user_id=userId,
        username="bob",
        full_name="Bob",
        timezone="",
        messages_count=messagesCount,
        metadata="",
        created_at=now,
        updated_at=now,
    )


def _makeHandler(*, getChatUserReturn: Optional[ChatUserDict]) -> Tuple[SpamHandler, AsyncMock]:
    """Build a ``SpamHandler`` whose ``cache.getChatUser`` is a spyable ``AsyncMock``.

    The handler is constructed via ``__new__`` (skipping ``__init__``) because
    ``_getUserInfoFreshIfMessagesLessThan`` is a pure consumer of
    ``self.cache.getChatUser`` and touches no other handler state. The attached
    ``cache`` is a ``Mock`` whose ``getChatUser`` is an ``AsyncMock`` returning
    *getChatUserReturn* on every call; tests assert on the returned spy's
    ``call_count`` and whether any call passed ``refresh=True``.

    Args:
        getChatUserReturn: Value the mock ``cache.getChatUser`` returns (a row
            dict, or None to simulate a cold cache / absent row).

    Returns:
        A ``(handler, getChatUserSpy)`` tuple where *handler* is the
        ``SpamHandler`` instance with a mock ``cache`` attached, and
        *getChatUserSpy* is the ``AsyncMock`` backing
        ``handler.cache.getChatUser``.
    """
    handler = SpamHandler.__new__(SpamHandler)  # bypass __init__
    getChatUserSpy = AsyncMock(return_value=getChatUserReturn)
    cache = AsyncMock()
    cache.getChatUser = getChatUserSpy
    handler.cache = cache
    return handler, getChatUserSpy


def _makeHandlerWithRefresh(
    *, cachedRow: Optional[ChatUserDict], refreshedRow: Optional[ChatUserDict]
) -> Tuple[SpamHandler, AsyncMock]:
    """Build a ``SpamHandler`` whose ``cache.getChatUser`` returns DISTINCT rows per call.

    Unlike ``_makeHandler`` (which uses ``return_value=`` and thus yields the SAME row
    on every call), this spy uses a ``side_effect`` that inspects the ``refresh``
    kwarg: a call WITHOUT ``refresh`` (or ``refresh=False``) returns *cachedRow*, and a
    call WITH ``refresh=True`` returns *refreshedRow*. This lets the refresh-path tests
    assert the helper REASSIGNS ``userInfo`` from the refreshed result — with a plain
    ``return_value`` spy, a missing reassignment would silently return the stale cached
    row (identical to the refreshed one) and the test would pass spuriously.

    Args:
        cachedRow: Row returned for the initial, non-refreshing ``getChatUser`` call.
        refreshedRow: Row returned for the ``getChatUser(refresh=True)`` call.

    Returns:
        A ``(handler, getChatUserSpy)`` tuple where *handler* is the ``SpamHandler``
        instance with a mock ``cache`` attached, and *getChatUserSpy* is the
        ``AsyncMock`` (with a ``side_effect``) backing ``handler.cache.getChatUser``.
    """

    def _getChatUser(*args: object, **kwargs: object) -> Optional[ChatUserDict]:
        if kwargs.get("refresh") is True:
            return refreshedRow
        return cachedRow

    handler = SpamHandler.__new__(SpamHandler)  # bypass __init__
    getChatUserSpy = AsyncMock(side_effect=_getChatUser)
    cache = AsyncMock()
    cache.getChatUser = getChatUserSpy
    handler.cache = cache
    return handler, getChatUserSpy


def _refreshWasCalled(getChatUserSpy: AsyncMock) -> bool:
    """Return True if any ``cache.getChatUser`` call passed ``refresh=True``.

    Args:
        getChatUserSpy: The ``AsyncMock`` backing ``cache.getChatUser`` whose
            recorded call list is inspected.

    Returns:
        True if at least one recorded call passed the keyword ``refresh=True``.
    """
    for call in getChatUserSpy.call_args_list:
        if call.kwargs.get("refresh") is True:
            return True
    return False


# Mirrors the production default-ish value of AUTO_SPAM_MAX_MESSAGES used at the
# two call sites. The actual value comes from per-chat settings at runtime; we
# pick a representative constant so the boundary semantics are explicit.
_MAX = 10


async def test_cachedCountAtOrAboveThreshold_doesNotRefresh() -> None:
    """A cached count >= threshold skips the refresh (monotonic value stays valid).

    Simulates the ``checkSpam`` gate (``userMessages >= maxCheckMessages``): once
    the cached count has reached the threshold it can only grow, so re-fetching
    would be a wasted DB hit. Asserts ``getChatUser`` is called exactly once
    (the initial read) and never with ``refresh=True``.
    """
    handler, getSpy = _makeHandler(getChatUserReturn=_makeRow(messagesCount=15))

    row = await handler._getUserInfoFreshIfMessagesLessThan(
        chatId=1, userId=2, messagesCountThreshold=_MAX  # checkSpam form: threshold unchanged
    )

    assert row is not None
    assert row["messages_count"] == 15
    assert getSpy.call_count == 1
    assert not _refreshWasCalled(getSpy)


async def test_cachedCountBelowThreshold_triggersRefresh() -> None:
    """A cached count < threshold triggers exactly one ``refresh=True`` re-fetch.

    The cached value might have drifted up past the threshold (the increment
    bypasses the cache), so it must be re-read. The spy returns a DISTINCT row on
    the refresh call (``messages_count`` rises from 3 to 12), so this also asserts
    the helper REASSIGNS ``userInfo`` from the refreshed result — a missing
    reassignment would return the stale cached count 3 and fail here. Asserts
    ``getChatUser`` is called exactly twice, the second call passes
    ``refresh=True``, and the returned row carries the refreshed count (12).
    """
    handler, getSpy = _makeHandlerWithRefresh(
        cachedRow=_makeRow(messagesCount=3),
        refreshedRow=_makeRow(messagesCount=12),
    )

    row = await handler._getUserInfoFreshIfMessagesLessThan(chatId=1, userId=2, messagesCountThreshold=_MAX)

    assert row is not None
    assert row["messages_count"] == 12  # refreshed value, NOT the stale cached 3
    assert getSpy.call_count == 2
    assert _refreshWasCalled(getSpy)


async def test_coldCache_returnsNoneAndDoesNotRefresh() -> None:
    """A cold cache / absent row returns None and does not attempt a refresh.

    When the initial read returns None there is nothing to compare against the
    threshold, so the helper short-circuits. Asserts ``getChatUser`` is called
    exactly once and never with ``refresh=True``.
    """
    handler, getSpy = _makeHandler(getChatUserReturn=None)

    row = await handler._getUserInfoFreshIfMessagesLessThan(chatId=1, userId=2, messagesCountThreshold=_MAX)

    assert row is None
    assert getSpy.call_count == 1
    assert not _refreshWasCalled(getSpy)


async def test_boundary_strictLessAndMarkAsSpamPlusOneForm() -> None:
    """Boundary semantics for the strict-``<`` refresh and the ``markAsSpam`` ``+1`` form.

    Two sub-cases pinned together because the ``+1`` form only makes sense
    relative to the strict-``<`` gate:

    1. cached ``messages_count == threshold`` with the threshold passed directly
       (the ``checkSpam`` form) → NO refresh, because the refresh condition is
       strictly ``<`` (equal does not trigger).
    2. cached ``messages_count == maxSpamMessages`` with the threshold passed as
       ``maxSpamMessages + 1`` (the ``markAsSpam`` form) → refresh DOES fire,
       because ``maxSpamMessages < maxSpamMessages + 1``. This closes the
       boundary false-ban window for ``markAsSpam``'s strict ``>`` gate.
    """
    # Sub-case 1: checkSpam form, cached == threshold → no refresh.
    handlerCheck, getSpyCheck = _makeHandler(getChatUserReturn=_makeRow(messagesCount=_MAX))
    rowCheck = await handlerCheck._getUserInfoFreshIfMessagesLessThan(chatId=1, userId=2, messagesCountThreshold=_MAX)
    assert rowCheck is not None
    assert rowCheck["messages_count"] == _MAX
    assert getSpyCheck.call_count == 1
    assert not _refreshWasCalled(getSpyCheck)

    # Sub-case 2: markAsSpam form (threshold = maxSpamMessages + 1), cached ==
    # maxSpamMessages → refresh fires (cached < maxSpamMessages + 1). The spy
    # returns a DISTINCT refreshed row so this also asserts the helper returns the
    # refreshed value, not the stale cached one.
    handlerMark, getSpyMark = _makeHandlerWithRefresh(
        cachedRow=_makeRow(messagesCount=_MAX),
        refreshedRow=_makeRow(messagesCount=_MAX + 5),
    )
    rowMark = await handlerMark._getUserInfoFreshIfMessagesLessThan(chatId=1, userId=2, messagesCountThreshold=_MAX + 1)
    assert rowMark is not None
    assert rowMark["messages_count"] == _MAX + 5  # refreshed value, NOT stale _MAX
    assert getSpyMark.call_count == 2
    assert _refreshWasCalled(getSpyMark)
