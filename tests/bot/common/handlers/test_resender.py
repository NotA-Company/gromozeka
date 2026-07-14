"""Tests for the resender forward feature.

Covers two layers of :mod:`internal.bot.common.handlers.resender`:

* The data model — :class:`ForwardTarget` (TypedDict shape) and the
  ``forwardTo`` field on :class:`ResendJob` (default, populated, and
  string representation).
* The forward loop inside :meth:`ResenderHandler.resendCronJob` —
  single target, multiple targets, multi-message-id forwarding,
  per-target failure isolation, no-forward-when-unconfigured,
  no-forward-when-sendMessage-empty, and no-forward-when-bot-not-injected.

All tests use the project's ``asyncio_mode = "auto"`` configuration.
The handler's database, bot, and message-sending methods are stubbed
at the instance level so the tests never touch a real bot, storage,
or database.
"""

import datetime
from typing import Dict, Generator, List, Optional, Tuple
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.resender import ForwardTarget, ResenderHandler, ResendJob
from internal.bot.models import BotProvider, ChatType, EnsuredMessage, MessageRecipient, MessageSender
from internal.models import MessageId

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _resetHandlerSingletons() -> Generator[None, None, None]:
    """Reset singleton state to prevent cross-test leakage.

    ``ResenderHandler.__init__`` (via ``BaseBotHandler``) resolves the
    ``CacheService``, ``QueueService``, ``StorageService``, and
    ``LLMService`` singletons. Only ``LLMService`` is reset by the shared
    autouse fixture in ``tests/conftest.py``; the other three are reset
    here so each test observes a fresh singleton instance.

    Yields:
        ``None`` — runs before and after each test.
    """
    from internal.services.cache.service import CacheService
    from internal.services.queue_service.service import QueueService
    from internal.services.storage.service import StorageService

    # Reset singleton instances before the test.
    for singletonCls in (CacheService, QueueService, StorageService):
        singletonCls._instance = None

    yield

    # Reset singleton instances after the test.
    for singletonCls in (CacheService, QueueService, StorageService):
        singletonCls._instance = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DATE: datetime.datetime = datetime.datetime(2026, 7, 3, 12, 0, 0, tzinfo=datetime.UTC)
"""Fixed timestamp used for every stubbed message row and sent message."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HandlerMocks = Dict[str, Mock]


def _makeConfigManager() -> Mock:
    """Build a stand-in ``ConfigManager`` for the resender constructor.

    Returns a ``Mock`` whose ``get("resender", ...)`` returns an empty
    jobs list (jobs are appended manually by tests for flexibility) and
    whose ``getBotConfig()`` returns a minimal bot config dict.

    Returns:
        ``Mock`` exposing ``get`` and ``getBotConfig`` with deterministic
        return values.
    """
    cm = Mock()
    cm.get = Mock(return_value={"jobs": []})
    cm.getBotConfig = Mock(return_value={"token": "test", "owners": []})
    return cm


def _makeDatabase() -> Mock:
    """Build a ``Database`` stub with the repositories the resender touches.

    Wires ``common.getSetting``/``setSetting`` (async, the cursor-persistence
    path), ``chatMessages.getChatMessagesSince`` (async, the new-message
    fetch), and a bare ``mediaAttachments`` placeholder. Tests reassign
    return values as needed.

    Returns:
        ``Mock`` whose ``common`` and ``chatMessages`` sub-attributes are
        themselves ``Mock`` objects with the async methods pre-stubbed.
    """
    db = Mock()
    db.common = Mock()
    db.common.getSetting = AsyncMock(return_value=None)
    db.common.setSetting = AsyncMock(return_value=None)
    db.chatMessages = Mock()
    db.chatMessages.getChatMessagesSince = AsyncMock(return_value=[])
    db.mediaAttachments = Mock()
    return db


def _makeEnsuredMessage(messageId: int = 100) -> EnsuredMessage:
    """Build a minimal :class:`EnsuredMessage` representing a sent message.

    The resender's forward loop reads only ``messageId`` from each item
    in the ``sendMessage`` result list, so this is the only field that
    must be populated for the forward assertions.

    Args:
        messageId: Telegram-flavoured int message ID (default 100).

    Returns:
        Fully constructed :class:`EnsuredMessage`.
    """
    return EnsuredMessage(
        sender=MessageSender(id=1, name="Bot", username="@bot"),
        recipient=MessageRecipient(id=2, chatType=ChatType.GROUP),
        messageId=messageId,
        date=BASE_DATE,
        messageText="resent text",
    )


def _makeMessageDict(*, text: str = "hello world", mediaGroupId: Optional[str] = None) -> Dict[str, object]:
    """Build a ``ChatMessageDict``-shaped row for stubbing ``getChatMessagesSince``.

    Only the keys the resender loop reads are populated:
    ``media_group_id``, ``message_text``, ``markup``, ``metadata``, and
    ``date``. The loop iterates ``message.items()`` to build a template
    substitution map, so extra keys are harmless but unnecessary.

    Args:
        text: Value for ``message_text`` (default ``"hello world"``).
        mediaGroupId: Value for ``media_group_id``; ``None`` (default)
            keeps the loop on the non-media-group path so the media
            attachment/storage code is not exercised.

    Returns:
        Dict matching the shape the resender loop reads.
    """
    return {
        "media_group_id": mediaGroupId,
        "message_text": text,
        "markup": None,
        "metadata": None,
        "date": BASE_DATE,
    }


def _makeJob(
    *,
    id: str = "test",
    sourceChatId: int = 1,
    targetChatId: int = 2,
    forwardTo: Optional[List[ForwardTarget]] = None,
) -> ResendJob:
    """Build a :class:`ResendJob` with sensible defaults for forward tests.

    Args:
        id: Job id (default ``"test"``).
        sourceChatId: Source chat id messages are read from (default 1).
        targetChatId: Target chat id messages are resent to (default 2).
        forwardTo: Optional list of forward targets; ``None`` lets the
            job normalise it to an empty list internally.

    Returns:
        Fully constructed :class:`ResendJob`.
    """
    return ResendJob(
        id=id,
        dataSource="ds",
        sourceChatId=sourceChatId,
        targetChatId=targetChatId,
        forwardTo=forwardTo,
        messageTypes=["user"],
    )


def _makeHandler(
    *,
    job: Optional[ResendJob] = None,
    messages: Optional[List[Dict[str, object]]] = None,
    sentMessages: Optional[List[EnsuredMessage]] = None,
) -> Tuple[ResenderHandler, HandlerMocks]:
    """Construct a :class:`ResenderHandler` with stubs ready for forward tests.

    The handler is built with an empty jobs config (jobs are appended
    manually), a stubbed database, and a stubbed bot whose
    ``forwardMessages`` is an ``AsyncMock``. ``sendMessage`` is overridden
    at the instance level so the real send path is never invoked.

    Args:
        job: Optional :class:`ResendJob` to set on ``handler.jobs``.
            Defaults to a no-forward job via :func:`_makeJob`.
        messages: Optional list of message-dict rows returned by
            ``getChatMessagesSince``. Defaults to a single text message
            via :func:`_makeMessageDict`.
        sentMessages: Optional list of :class:`EnsuredMessage` returned
            by the stubbed ``sendMessage``. Defaults to a single message
            with ``messageId=100``.

    Returns:
        Tuple ``(handler, mocks)`` where ``mocks`` exposes ``db``, ``bot``,
        ``sendMessage``, and ``configManager`` for direct assertion.
    """
    cm = _makeConfigManager()
    db = _makeDatabase()
    msgList = messages if messages is not None else [_makeMessageDict()]
    db.chatMessages.getChatMessagesSince = AsyncMock(return_value=msgList)

    handler = ResenderHandler(
        configManager=cm,
        database=db,
        botProvider=BotProvider.TELEGRAM,
    )

    handler.jobs = [job if job is not None else _makeJob()]

    # Stub the bot + forwardMessages.
    bot = Mock()
    bot.forwardMessages = AsyncMock(return_value=[])
    handler._bot = bot

    # Stub sendMessage at the instance level so the real send path is skipped.
    sendMessageMock = AsyncMock(return_value=sentMessages if sentMessages is not None else [_makeEnsuredMessage()])
    handler.sendMessage = sendMessageMock

    mocks: HandlerMocks = {
        "db": db,
        "bot": bot,
        "sendMessage": sendMessageMock,
        "configManager": cm,
    }
    return handler, mocks


# ---------------------------------------------------------------------------
# 1. Data model tests
# ---------------------------------------------------------------------------


class TestForwardTargetDataModel:
    """Tests for the :class:`ForwardTarget` TypedDict and its usage on :class:`ResendJob`."""

    def testForwardTargetRequiredChatId(self) -> None:
        """``ForwardTarget(chatId=...)`` constructs and ``target["chatId"]`` returns the value.

        TypedDicts are plain dicts at runtime, so construction never
        raises; the required-field contract is enforced only by the type
        checker. This test pins the runtime behaviour: the value passed
        for ``chatId`` round-trips through subscript access.
        """
        target: ForwardTarget = ForwardTarget(chatId=-456)
        assert target["chatId"] == -456

    def testForwardTargetOptionalFields(self) -> None:
        """Optional ``threadId``/``notify`` keys are absent unless explicitly set.

        ``ForwardTarget(chatId=...)`` yields a dict with only ``chatId``;
        adding ``threadId`` and ``notify`` makes all three keys present.
        The resender loop reads these via ``target.get("threadId")`` /
        ``target.get("notify")``, so key absence (not ``None``) is the
        signal for "use platform default".
        """
        minimal: ForwardTarget = ForwardTarget(chatId=-456)
        assert "chatId" in minimal
        assert "threadId" not in minimal
        assert "notify" not in minimal

        full: ForwardTarget = ForwardTarget(chatId=-456, threadId=5, notify=True)
        assert full["chatId"] == -456
        # Optional keys are present when explicitly set; use ``.get`` so the
        # assertion reads the value without tripping TypedDict access checks.
        assert "threadId" in full
        assert full.get("threadId") == 5
        assert "notify" in full
        assert full.get("notify") is True

    def testResendJobWithoutForwardTo(self) -> None:
        """A job constructed without ``forwardTo`` has an empty forward list.

        ``ResendJob.__init__`` normalises a missing ``forwardTo`` to an
        empty list (not ``None``); the resender loop treats an empty list
        as falsy and skips forwarding entirely. This pins the default so
        a future refactor cannot silently flip it to ``None`` and break
        the ``if job.forwardTo`` gate.
        """
        job = _makeJob()
        assert job.forwardTo == []
        assert not job.forwardTo

    def testResendJobWithForwardTo(self) -> None:
        """A job constructed with ``forwardTo`` retains the list verbatim.

        Each entry is stored as-is (a plain dict matching
        :class:`ForwardTarget`); the loop reads ``chatId``/``threadId``/
        ``notify`` from it directly.
        """
        job = _makeJob(forwardTo=[ForwardTarget(chatId=-456)])
        assert isinstance(job.forwardTo, list)
        assert len(job.forwardTo) == 1
        assert job.forwardTo[0]["chatId"] == -456

    def testResendJobStrWithForwardTo(self) -> None:
        """``str(job)`` includes the configured forward-to chat IDs.

        ``ResendJob.__str__`` renders every slot (except ``_lock``), so
        the ``forwardTo`` list — and therefore the target chat IDs — must
        appear in the string. This keeps job logging self-describing.
        """
        job = _makeJob(forwardTo=[ForwardTarget(chatId=-456), ForwardTarget(chatId=-789)])
        rendered = str(job)
        assert "forwardTo=" in rendered
        assert "-456" in rendered
        assert "-789" in rendered


# ---------------------------------------------------------------------------
# 2. Forward loop tests
# ---------------------------------------------------------------------------


# NOTE: the autouse _noOpSendPacingSleep fixture no-ops asyncio.sleep for this class.
# Media-group forwarding tests MUST go in a separate class — the production
# media-group wait loop (resender.py ~line 383-389) advances via real
# asyncio.sleep and would infinite-loop if no-op'd.
class TestResendCronJobForwarding:
    """Tests for the forward loop inside :meth:`ResenderHandler.resendCronJob`.

    Each test drives a single resender tick with one stubbed message and
    asserts on the resulting ``forwardMessages`` calls. The primary
    resend (``sendMessage``) is stubbed to succeed; only the additional
    forward step varies between tests.
    """

    @pytest.fixture(autouse=True)
    def _noOpSendPacingSleep(self) -> Generator[None, None, None]:
        """No-op the inter-send / inter-forward pacing sleeps.

        ``ResenderHandler.resendCronJob`` awaits ``asyncio.sleep`` for
        two production pacing reasons (neither asserted on by any test
        here):

        * ``asyncio.sleep(messageSendDelay)`` (``resender.py`` ~line 476)
          — an exponential-backoff cushion between resent messages
          (initial value ``0.25``, doubling up to 10s).
        * ``asyncio.sleep(0.1)`` (``resender.py`` ~line 474) — a brief
          pause between forward targets to avoid rate-limit issues.

        Left unmocked these cost ~0.25-0.45s of real wall-clock per test
        (~2.7s across the eight forwarding tests). Patched to an async
        no-op so the suite exercises the identical forward logic without
        paying the pacing tax.

        The media-group readiness wait (``resender.py`` ~line 389,
        ``asyncio.sleep(mediaGroupDelaySecs - age)`` inside a ``while``
        loop) is a *timing-condition* sleep, not pacing — but it is
        unreachable here: every test stubs messages via
        :func:`_makeMessageDict` with ``mediaGroupId=None``, so the
        ``if message["media_group_id"]`` gate is always false. No-op'ing
        ``asyncio.sleep`` is therefore safe for this class; the
        timing-condition loop is never entered.

        A bounded-call guard wraps the no-op so a future test that does set
        a real ``mediaGroupId`` fails loudly (``AssertionError`` after 50
        calls) instead of busy-spinning forever inside the readiness wait.

        Yields:
            ``None`` — patches ``asyncio.sleep`` for the duration of
            each test, then restores it.
        """
        callCount = 0

        async def _boundedNoOpSleep(_seconds: float) -> None:
            nonlocal callCount
            callCount += 1
            if callCount > 50:
                raise AssertionError(
                    "asyncio.sleep called 50 times — possible time-based loop "
                    "reached under no-op sleep (e.g. the media-group readiness wait)"
                )

        with patch(
            "internal.bot.common.handlers.resender.asyncio.sleep",
            new=_boundedNoOpSleep,
        ):
            yield

    async def testCronJobForwardsToSingleTarget(self) -> None:
        """A job with one ``forwardTo`` target forwards the resent message once.

        After the primary resend succeeds, the loop must call
        ``self._bot.forwardMessages`` with ``fromChatId`` equal to the
        job's ``targetChatId`` (where the message was just resent),
        ``messageIds`` lifted from the ``sendMessage`` result, and
        ``toChatId`` equal to the forward target. Optional keys absent
        on the target are forwarded as ``None`` (platform default).
        """
        job = _makeJob(targetChatId=2, forwardTo=[ForwardTarget(chatId=-456)])
        handler, mocks = _makeHandler(job=job)

        await handler.resendCronJob()

        bot = mocks["bot"]
        bot.forwardMessages.assert_awaited_once()
        kwargs = bot.forwardMessages.call_args.kwargs
        assert kwargs["fromChatId"] == 2
        assert kwargs["toChatId"] == -456
        assert kwargs["messageIds"] == [MessageId(100)]
        # Optional keys absent on the target → forwarded as None.
        assert kwargs["threadId"] is None
        assert kwargs["notify"] is None

    async def testCronJobForwardsWithOptionalFields(self) -> None:
        """A target with ``threadId``/``notify`` forwards them through.

        The loop reads ``target.get("threadId")`` and
        ``target.get("notify")`` and passes them straight to
        ``forwardMessages``, so a fully-populated target must surface
        both values on the call rather than collapsing them to ``None``.
        """
        job = _makeJob(
            targetChatId=2,
            forwardTo=[ForwardTarget(chatId=-456, threadId=5, notify=False)],
        )
        handler, mocks = _makeHandler(job=job)

        await handler.resendCronJob()

        bot = mocks["bot"]
        bot.forwardMessages.assert_awaited_once()
        kwargs = bot.forwardMessages.call_args.kwargs
        assert kwargs["toChatId"] == -456
        assert kwargs["threadId"] == 5
        assert kwargs["notify"] is False

    async def testCronJobForwardsToMultipleTargets(self) -> None:
        """A job with two ``forwardTo`` targets forwards to each, independently.

        The loop iterates ``job.forwardTo`` and calls ``forwardMessages``
        once per entry, preserving order. Both targets are attempted even
        though they share the same source message.
        """
        job = _makeJob(
            targetChatId=2,
            forwardTo=[ForwardTarget(chatId=-456), ForwardTarget(chatId=-789)],
        )
        handler, mocks = _makeHandler(job=job)

        await handler.resendCronJob()

        bot = mocks["bot"]
        assert bot.forwardMessages.await_count == 2
        toChatIds = [call.kwargs["toChatId"] for call in bot.forwardMessages.call_args_list]
        assert toChatIds == [-456, -789]
        # Both forwards share the same source message / fromChatId.
        for call in bot.forwardMessages.call_args_list:
            assert call.kwargs["fromChatId"] == 2
            assert call.kwargs["messageIds"] == [MessageId(100)]

    async def testCronJobForwardsMultipleMessageIds(self) -> None:
        """A multi-message primary resend forwards every produced message id.

        When ``sendMessage`` returns more than one :class:`EnsuredMessage`
        (e.g. a media group split across several sends), the forward loop
        lifts ``messageId`` from each entry and forwards them all in a
        single ``forwardMessages`` call.
        """
        job = _makeJob(targetChatId=2, forwardTo=[ForwardTarget(chatId=-456)])
        handler, mocks = _makeHandler(
            job=job,
            sentMessages=[_makeEnsuredMessage(100), _makeEnsuredMessage(101)],
        )

        await handler.resendCronJob()

        bot = mocks["bot"]
        bot.forwardMessages.assert_awaited_once()
        kwargs = bot.forwardMessages.call_args.kwargs
        assert kwargs["fromChatId"] == 2
        assert kwargs["messageIds"] == [MessageId(100), MessageId(101)]

    async def testCronJobForwardFailureDoesNotBlock(self) -> None:
        """A forward failure on one target does not block the others or the cursor.

        The per-target forward is wrapped in its own try/except, so an
        exception on the first target is logged and swallowed, the second
        target is still attempted, and the primary resend's success is
        reflected by ``lastMessageDate`` being persisted via
        ``setSetting`` regardless of the forward outcome.
        """
        job = _makeJob(
            targetChatId=2,
            forwardTo=[ForwardTarget(chatId=-456), ForwardTarget(chatId=-789)],
        )
        handler, mocks = _makeHandler(job=job)
        # First forward raises, second succeeds.
        mocks["bot"].forwardMessages = AsyncMock(side_effect=[RuntimeError("forward failed"), [MessageId(200)]])

        await handler.resendCronJob()

        bot = mocks["bot"]
        # Both targets were attempted despite the first raising.
        assert bot.forwardMessages.await_count == 2
        # Cursor advancement still happened (primary resend succeeded), exactly once.
        mocks["db"].common.setSetting.assert_awaited_once()
        setCall = mocks["db"].common.setSetting.call_args
        assert setCall.args[0] == "resender:test:lastMessageDate"

    async def testCronJobNoForwardWhenNotConfigured(self) -> None:
        """A job with no ``forwardTo`` never calls ``forwardMessages``.

        The ``if job.forwardTo`` gate is falsy for the default empty
        list, so the forward step is skipped entirely even though the
        primary resend still runs.
        """
        job = _makeJob()  # no forwardTo → []
        handler, mocks = _makeHandler(job=job)

        await handler.resendCronJob()

        mocks["bot"].forwardMessages.assert_not_called()
        # Primary resend still happened.
        mocks["sendMessage"].assert_awaited_once()

    async def testCronJobNoForwardWhenSendMessageEmpty(self) -> None:
        """An empty ``sendMessage`` result skips the forward step.

        When the primary resend produces no sent messages (``messageIds``
        is empty), the ``if ... and messageIds`` guard short-circuits and
        ``forwardMessages`` is never called, even with a configured
        forward target. The primary send is still attempted because the
        source message has text.
        """
        job = _makeJob(targetChatId=2, forwardTo=[ForwardTarget(chatId=-456)])
        handler, mocks = _makeHandler(job=job, sentMessages=[])

        await handler.resendCronJob()

        mocks["bot"].forwardMessages.assert_not_called()
        # The primary send was still attempted (message had text).
        mocks["sendMessage"].assert_awaited_once()

    async def testCronJobNoForwardWhenBotNotInjected(self) -> None:
        """A configured ``forwardTo`` is skipped when the bot instance is absent.

        The forward gate is ``job.forwardTo and self._bot is not None and
        messageIds``. Even with a populated ``forwardTo`` and a successful
        primary resend, a ``None`` ``_bot`` short-circuits the forward
        step. The primary resend still runs because ``sendMessage`` is
        stubbed at the instance level (it does not consult ``self._bot``).
        """
        job = _makeJob(targetChatId=2, forwardTo=[ForwardTarget(chatId=-456)])
        handler, mocks = _makeHandler(job=job)
        handler._bot = None

        await handler.resendCronJob()

        mocks["bot"].forwardMessages.assert_not_called()
        # Primary resend still happened.
        mocks["sendMessage"].assert_awaited_once()
