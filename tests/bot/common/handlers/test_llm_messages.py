"""Tests for :class:`LLMMessageHandler`.

Three feature areas are covered, each in its own class:

* :class:`TestBotAnswerProbabilityGate` — the ``BOT_ANSWER_PROBABILITY`` gate
  in ``newMessageHandler``. When a message arrives from a sender whose username
  ends with ``"bot"`` (likely another bot), the handler consults the per-chat
  ``BOT_ANSWER_PROBABILITY`` setting and probabilistically skips the message:

  * ``0.0`` — never answer bots (always ``SKIPPED``),
  * ``1.0`` — always answer bots (never skipped),
  * anything in between — answer with that probability.

  The downstream handlers (``handleReply`` / ``handleMention`` /
  ``handleRandomMessage``) are stubbed so the gate is the only logic under test.
  ``BotProvider.MAX`` is used so the Telegram-only ``is_automatic_forward``
  branch is skipped.

* :class:`TestRandomAnswerPromptAndSkipSentinel` — the random-answer-context
  feature: the ``RANDOM_ANSWER_PROMPT`` system-message fragment (appended only
  inside ``handleRandomMessage``) and the ``<skip>`` abstention sentinel
  (``LLMReplyOutcome.SKIPPED_BY_MODEL``). These tests drive the real
  ``handleRandomMessage`` / ``handleReply`` / ``handleMention`` /
  ``_sendLLMChatMessage`` code paths with only leaf dependencies mocked.

* :class:`TestMediaDescriptionExtraction` — the ``<media-description>`` tag
  extraction block in ``_sendLLMChatMessage``. Pins both the corrected
  extraction behaviour (trailing/leading text preserved) and the intentional
  limitations (JSON-format skip, pure-middle-tag gate, single-tag handling, and
  the tag-only→empty-text-sentinel interaction). Tests call
  ``_sendLLMChatMessage`` directly.
"""

import contextlib
import datetime
from collections.abc import Awaitable, Callable, Sequence
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.base import HandlerResultStatus
from internal.bot.common.handlers.llm_messages import LLMMessageHandler, LLMReplyOutcome
from internal.bot.constants import ToolName
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    EnsuredMessage,
    MentionCheckResult,
    MessageRecipient,
    MessageSender,
)
from internal.models import MessageId
from internal.services.cache.service import CacheService
from internal.services.queue_service.service import QueueService
from internal.services.storage.service import StorageService
from lib.ai import ModelMessage, ModelResultStatus, ModelRunResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mockConfig() -> Mock:
    """Build a minimal ConfigManager stub.

    Returns:
        Mock: A ``ConfigManager`` whose ``getBotConfig()`` returns a token/owners
        dict sufficient for ``BaseBotHandler.__init__``.
    """
    from internal.config.manager import ConfigManager

    cm = Mock(spec=ConfigManager)
    cm.getBotConfig.return_value = {"token": "test_token", "owners": [123456]}
    return cm


@pytest.fixture
def mockDb() -> Mock:
    """Build a Database stub.

    Returns:
        Mock: A ``Database`` spec mock; the gate does not touch the DB but
        ``BaseBotHandler.__init__`` stores it.
    """
    from internal.database import Database

    return Mock(spec=Database)


@pytest.fixture
def handler(mockConfig: Mock, mockDb: Mock) -> LLMMessageHandler:
    """Construct an :class:`LLMMessageHandler` with all deps mocked.

    The autouse ``resetLlmServiceSingleton`` fixture has already reset the
    ``LLMService`` singleton, so ``LLMService.getInstance()`` called from the
    constructor returns a fresh instance. The three other singletons are
    patched to return bare mocks.

    Downstream handlers (``handleReply`` / ``handleMention`` /
    ``handleRandomMessage``) are stubbed to return ``False`` so a message that
    passes the gate yields ``HandlerResultStatus.NEXT`` without invoking the
    LLM. ``getChatSettings`` is stubbed with a configurable probability (see
    ``_chatSettings``); individual tests override the return value.

    Args:
        mockConfig: ConfigManager stub.
        mockDb: Database stub.

    Returns:
        A handler wired for gate-only testing.
    """
    with (
        patch.object(CacheService, "getInstance", return_value=Mock()),
        patch.object(QueueService, "getInstance", return_value=Mock()),
        patch.object(StorageService, "getInstance", return_value=Mock()),
    ):
        h = LLMMessageHandler(  # type: ignore[call-arg]
            configManager=mockConfig,
            database=mockDb,
            botProvider=BotProvider.MAX,
        )

    h.handleReply = AsyncMock(return_value=False)  # type: ignore[method-assign]
    h.handleMention = AsyncMock(return_value=False)  # type: ignore[method-assign]
    h.handleRandomMessage = AsyncMock(return_value=False)  # type: ignore[method-assign]
    h.getChatSettings = AsyncMock(return_value=_chatSettings(0.0))  # type: ignore[method-assign]
    return h


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chatSettings(botAnswerProbability: float) -> ChatSettingsDict:
    """Build a chat-settings dict carrying the bot-answer probability.

    Args:
        botAnswerProbability: Value for ``BOT_ANSWER_PROBABILITY`` (0.0–1.0).

    Returns:
        Mapping with ``BOT_ANSWER_PROBABILITY`` set to the given float (the
        gate reads it via ``.toFloat()``).
    """
    return {
        ChatSettingsKey.BOT_ANSWER_PROBABILITY: ChatSettingsValue(str(botAnswerProbability)),
    }


def _makeEnsuredMessage(*, username: str, chatId: int = 100) -> Mock:
    """Build a mock :class:`EnsuredMessage` for the gate.

    Args:
        username: Sender username (the gate lowercases + checks ``endswith("bot")``).
        chatId: Recipient chat id (default 100, private).

    Returns:
        Mock: Spec-restricted ``EnsuredMessage`` with ``sender`` and
        ``recipient`` populated. Only the fields read before the downstream
        handlers are needed.
    """
    msg = Mock(spec=EnsuredMessage)
    msg.sender = MessageSender(id=7, name="Sender", username=username)
    msg.recipient = MessageRecipient(id=chatId, chatType=ChatType.PRIVATE)
    msg.messageId = MessageId(42)
    return msg


# ---------------------------------------------------------------------------
# Tests: bot-answer probability gate
# ---------------------------------------------------------------------------


class TestBotAnswerProbabilityGate:
    """Tests for the ``BOT_ANSWER_PROBABILITY`` gate in ``newMessageHandler``."""

    async def testProbabilityZeroSkipsAllBotSenders(self, handler: LLMMessageHandler) -> None:
        """``BOT_ANSWER_PROBABILITY = 0.0`` → bot message is always skipped.

        Args:
            handler: Handler fixture (probability defaulted to 0.0).
        """
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(0.0))  # type: ignore[method-assign]
        ensured = _makeEnsuredMessage(username="somebot")

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.SKIPPED
        handler.handleReply.assert_not_awaited()  # type: ignore[attr-defined]

    async def testProbabilityOneNeverSkipsBotSenders(self, handler: LLMMessageHandler) -> None:
        """``BOT_ANSWER_PROBABILITY = 1.0`` → bot message is never skipped.

        ``random.random()`` is patched to a near-maximal value (0.99) to prove
        that even a high roll passes when the probability is 1.0 (a roll is
        always ``< 1.0``).

        Args:
            handler: Handler fixture.
        """
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(1.0))  # type: ignore[method-assign]
        ensured = _makeEnsuredMessage(username="somebot")

        with patch("random.random", return_value=0.99):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        handler.handleReply.assert_awaited_once()  # type: ignore[attr-defined]

    async def testRandomRollAboveProbabilitySkips(self, handler: LLMMessageHandler) -> None:
        """Roll > probability → bot message skipped.

        Args:
            handler: Handler fixture.
        """
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(0.3))  # type: ignore[method-assign]
        ensured = _makeEnsuredMessage(username="somebot")

        with patch("random.random", return_value=0.5):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.SKIPPED
        handler.handleReply.assert_not_awaited()  # type: ignore[attr-defined]

    async def testRandomRollBelowProbabilityPasses(self, handler: LLMMessageHandler) -> None:
        """Roll <= probability → bot message passes the gate.

        Args:
            handler: Handler fixture.
        """
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(0.3))  # type: ignore[method-assign]
        ensured = _makeEnsuredMessage(username="somebot")

        with patch("random.random", return_value=0.2):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        handler.handleReply.assert_awaited_once()  # type: ignore[attr-defined]

    async def testNonBotUsernameNotGated(self, handler: LLMMessageHandler) -> None:
        """Sender whose username does not end in ``"bot"`` bypasses the gate.

        Even with probability 0.0, a normal user is not gated; the handler
        must not even fetch chat settings for the gate.

        Args:
            handler: Handler fixture.
        """
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(0.0))  # type: ignore[method-assign]
        ensured = _makeEnsuredMessage(username="alice")

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        handler.getChatSettings.assert_not_awaited()  # type: ignore[attr-defined]
        handler.handleReply.assert_awaited_once()  # type: ignore[attr-defined]

    async def testEmptyUsernameNotGated(self, handler: LLMMessageHandler) -> None:
        """An empty username is treated as "not a bot" and bypasses the gate.

        Args:
            handler: Handler fixture.
        """
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(0.0))  # type: ignore[method-assign]
        ensured = _makeEnsuredMessage(username="")

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        handler.getChatSettings.assert_not_awaited()  # type: ignore[attr-defined]

    async def testMixedCaseBotUsernameDetected(self, handler: LLMMessageHandler) -> None:
        """Usernames like ``"MyBot"`` are detected (case-insensitive suffix).

        Args:
            handler: Handler fixture.
        """
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(0.0))  # type: ignore[method-assign]
        ensured = _makeEnsuredMessage(username="MyBot")

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.SKIPPED
        handler.handleReply.assert_not_awaited()  # type: ignore[attr-defined]

    async def testBotAnswerProbabilityExactBoundary(self, handler: LLMMessageHandler) -> None:
        """When ``randomRoll == probability`` the message is NOT skipped.

        The gate uses strict ``>`` (``roll > probability``), so an exact match
        counts as a pass. With probability 0.3 and a patched roll of 0.3, the
        message must reach the downstream handlers.

        Args:
            handler: Handler fixture.
        """
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(0.3))  # type: ignore[method-assign]
        ensured = _makeEnsuredMessage(username="somebot")

        with patch("random.random", return_value=0.3):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        handler.handleReply.assert_awaited_once()  # type: ignore[attr-defined]

    async def testBotAnswerProbabilityNegative(self, handler: LLMMessageHandler) -> None:
        """A negative probability is treated as 0 (always skipped).

        The gate checks ``botAnswerProbability <= 0.0`` before rolling, so a
        negative value must short-circuit to ``SKIPPED`` without ever calling
        ``random.random()``.

        Args:
            handler: Handler fixture.
        """
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(-0.5))  # type: ignore[method-assign]
        ensured = _makeEnsuredMessage(username="somebot")

        with patch("random.random", return_value=0.0) as mockRandom:
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.SKIPPED
        mockRandom.assert_not_called()
        handler.handleReply.assert_not_awaited()  # type: ignore[attr-defined]

    async def testBotAnswerProbabilityAboveOne(self, handler: LLMMessageHandler) -> None:
        """A probability above 1.0 never skips (always passes).

        ``random.random()`` is always ``< 1.0``, so any probability ``> 1.0``
        makes ``roll > probability`` impossible — the message always reaches
        downstream handlers.

        Args:
            handler: Handler fixture.
        """
        handler.getChatSettings = AsyncMock(return_value=_chatSettings(1.5))  # type: ignore[method-assign]
        ensured = _makeEnsuredMessage(username="somebot")

        with patch("random.random", return_value=0.99):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        handler.handleReply.assert_awaited_once()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Random-answer context + <skip> abstainment
#
# The fixtures/helpers above target the probability gate only. The tests below
# exercise the real handleRandomMessage / handleReply / handleMention /
# _sendLLMChatMessage code paths: the three handlers are left LIVE and only
# leaf dependencies (getChatSettings, startTyping, sendMessage, isAdmin,
# llmService.generateTextViaLLM / generateImage, db.chatMessages) are mocked.
# ---------------------------------------------------------------------------

#: Distinctive substring embedded in the test RANDOM_ANSWER_PROMPT value so
#: assertions can confirm the fragment was (or was not) appended to the system
#: message. Carries a slice of the real Russian default for realism.
RANDOM_PROMPT_MARKER: str = "СЕЙЧАС К ТЕБЕ НЕ ОБРАЩАЮТСЯ [TEST-RANDOM-MARKER]"


def _fullChatSettings(
    *,
    randomAnswerProbability: float = 1.0,
    llmMessageFormat: str = "text",
) -> ChatSettingsDict:
    """Build a chat-settings dict covering every key the non-condensing paths read.

    A sparse dict raises ``KeyError`` because production code indexes
    ``chatSettings[KEY]`` directly (see the "Chat Settings Must Be Complete
    Dicts" note). This helper covers every ``ChatSettingsKey`` read on the
    non-condensing paths exercised by the tests below
    (``handleRandomMessage``'s non-condensing branch, ``handleReply``,
    ``handleMention``, ``_sendLLMChatMessage``). The condensing branch
    (``CHAT_MODEL``, ``CONDENSING_MODEL``, ``CONDENSING_PROMPT``,
    ``CONDENSING_SYSTEM_PROMPT``) is intentionally omitted because no test
    here triggers it.

    Args:
        randomAnswerProbability: Value for ``RANDOM_ANSWER_PROBABILITY`` (the
            random-roll threshold). Defaults to ``1.0`` (always answer).
        llmMessageFormat: Value for ``LLM_MESSAGE_FORMAT``. Defaults to
            ``"text"`` so the JSON-unwrap branch in ``_sendLLMChatMessage``
            runs (needed by the JSON-wrapped ``<skip>`` test).

    Returns:
        A complete :class:`ChatSettingsDict` with deterministic test values.
    """
    return {
        ChatSettingsKey.RANDOM_ANSWER_PROBABILITY: ChatSettingsValue(str(randomAnswerProbability)),
        ChatSettingsKey.RANDOM_ANSWER_TO_ADMIN: ChatSettingsValue("true"),
        ChatSettingsKey.RANDOM_ANSWER_PROMPT: ChatSettingsValue(RANDOM_PROMPT_MARKER),
        ChatSettingsKey.CHAT_PROMPT: ChatSettingsValue("CHAT_PROMPT_BASE"),
        ChatSettingsKey.CHAT_PROMPT_SUFFIX: ChatSettingsValue("CHAT_PROMPT_SUFFIX_BASE"),
        ChatSettingsKey.LLM_MESSAGE_FORMAT: ChatSettingsValue(llmMessageFormat),
        ChatSettingsKey.USE_TOOLS: ChatSettingsValue("false"),
        ChatSettingsKey.ALLOW_SANDBOX: ChatSettingsValue("false"),
        ChatSettingsKey.FALLBACK_HAPPENED_PREFIX: ChatSettingsValue(""),
        ChatSettingsKey.TOOLS_USED_PREFIX: ChatSettingsValue(""),
        ChatSettingsKey.INTERMEDIATE_MESSAGE_PREFIX: ChatSettingsValue(""),
        ChatSettingsKey.ALLOW_REPLY: ChatSettingsValue("true"),
        ChatSettingsKey.ALLOW_MENTION: ChatSettingsValue("true"),
        ChatSettingsKey.BOT_NICKNAMES: ChatSettingsValue(""),
        ChatSettingsKey.BOT_ANSWER_PROBABILITY: ChatSettingsValue("1.0"),
        # Phase 3a: memory-injection default off so the chat-time useTools gate
        # (ADD_MEMORY/SEARCH_MEMORIES) hides the memory tools by default. Tests
        # that exercise the gate override MEMORY_INJECTION_ENABLED inline by
        # building a settings dict with it set to "true" directly.
        ChatSettingsKey.MEMORY_INJECTION_ENABLED: ChatSettingsValue("false"),
    }


def _liveEnsuredMessage(
    *,
    chatId: int = -100,
    senderId: int = 7,
    senderName: str = "Alice",
    isReply: bool = False,
) -> EnsuredMessage:
    """Build a real :class:`EnsuredMessage` for live-handler tests.

    Unlike ``_makeEnsuredMessage`` (which returns a spec mock for the gate
    tests), this returns a fully constructed :class:`EnsuredMessage` so the
    real ``handle*`` methods can read ``recipient`` / ``sender`` / ``messageId``
    / ``replyId`` / ``threadId`` / ``metadata``. Per-test code mocks the few
    methods that would otherwise touch the DB (``toModelMessageList``,
    ``updateMediaContent``, ``toModelMessage``, ``getEnsuredRepliedToMessage``).

    Args:
        chatId: Recipient chat id (negative → group).
        senderId: Sender user id.
        senderName: Sender display name.
        isReply: If True, mark the message as a reply (sets ``replyId``).

    Returns:
        A constructed :class:`EnsuredMessage`.
    """
    em = EnsuredMessage(
        sender=MessageSender(id=senderId, name=senderName, username="@alice"),
        recipient=MessageRecipient(id=chatId, chatType=ChatType.GROUP),
        messageId=42,
        date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText="hello world",
    )
    if isReply:
        em.isReply = True
        em.replyId = MessageId(55)
    return em


def _modelRunResult(resultText: str) -> ModelRunResult:
    """Build a :class:`ModelRunResult` with ``FINAL`` status and given text.

    Args:
        resultText: The ``resultText`` the mocked LLM "returned".

    Returns:
        A ``ModelRunResult`` with ``isFallback``/``isToolsUsed`` False and no
        tool-usage history (the paths under test do not exercise those branches).
    """
    return ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=resultText)


def _imageRunResult() -> ModelRunResult:
    """Build a :class:`ModelRunResult` simulating a successful image generation.

    The image-gen branch in ``_sendLLMChatMessage`` requires
    ``status == ModelResultStatus.FINAL`` and ``mediaData is not None`` to send
    the photo and return ``SENT``. This helper satisfies both.

    Returns:
        A ``ModelRunResult`` with ``FINAL`` status, non-empty ``mediaData``,
        and ``isFallback`` False (so the ``FALLBACK_HAPPENED_PREFIX`` read
        inside the image branch is not exercised).
    """
    return ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText="",
        mediaData=b"fake_image",
    )


def _typingCtxManager() -> AsyncMock:
    """Build a double usable as ``async with await startTyping(...) as tm``.

    The ``handle*`` methods open a typing context. The returned object is an
    ``AsyncMock`` whose ``__aenter__`` yields a typing-manager ``AsyncMock``.

    Returns:
        An async-context-manager mock.
    """
    typingManager = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=typingManager)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _captureGenerate(
    resultText: str,
) -> tuple[Callable[..., Awaitable[ModelRunResult]], dict[str, Sequence[ModelMessage]]]:
    """Build a generateTextViaLLM double that captures its messages arg.

    Args:
        resultText: The ``resultText`` the double returns.

    Returns:
        A ``(generate, captured)`` pair. After the handler runs, ``captured``
        holds key ``"messages"`` → the ``Sequence[ModelMessage]`` passed to the
        LLM as the first positional argument.
    """
    captured: dict[str, Sequence[ModelMessage]] = {}

    async def generate(messages: Sequence[ModelMessage], *args: object, **kwargs: object) -> ModelRunResult:
        captured["messages"] = messages
        return _modelRunResult(resultText)

    return generate, captured


@pytest.fixture
def liveHandler(mockConfig: Mock) -> LLMMessageHandler:
    """Construct an :class:`LLMMessageHandler` with leaf deps mocked, handlers LIVE.

    Unlike the ``handler`` fixture (which stubs ``handleReply`` /
    ``handleMention`` / ``handleRandomMessage`` to exercise only the gate), this
    fixture leaves the three handlers un-stubbed so tests can drive the real
    prompt-assembly and ``<skip>``-sentinel code. Only leaf dependencies are
    mocked: ``getChatSettings``, ``startTyping``, ``sendMessage``, ``isAdmin``,
    ``llmService.generateImage``, and the ``db.chatMessages`` repository.

    Per-test code overrides ``llmService.generateTextViaLLM`` and, where
    needed, ``getThreadByMessageForLLM`` / ``getBotId`` / ``checkEMMentionsMe``.

    Args:
        mockConfig: Shared ``ConfigManager`` spec mock fixture.

    Returns:
        A handler wired for live-path testing.
    """
    # Plain Mock (not spec=Database) is deliberate: ``chatMessages`` is an
    # instance attribute set in ``Database.__init__``, so ``Mock(spec=Database)``
    # rejects accessing it, and ``handleRandomMessage`` reads
    # ``db.chatMessages.getChatMessagesSince``.
    mockDb = Mock()
    mockDb.chatMessages.getChatMessagesSince = AsyncMock(return_value=[])
    with (
        patch.object(CacheService, "getInstance", return_value=Mock()),
        patch.object(QueueService, "getInstance", return_value=Mock()),
        patch.object(StorageService, "getInstance", return_value=Mock()),
    ):
        h = LLMMessageHandler(  # type: ignore[call-arg]
            configManager=mockConfig,
            database=mockDb,
            botProvider=BotProvider.MAX,
        )
    h.getChatSettings = AsyncMock(return_value=_fullChatSettings())  # type: ignore[method-assign]
    h.startTyping = AsyncMock(return_value=_typingCtxManager())  # type: ignore[method-assign]
    h.isAdmin = AsyncMock(return_value=False)  # type: ignore[method-assign]
    h.sendMessage = AsyncMock(return_value=[Mock()])  # type: ignore[method-assign]
    h.llmService.generateImage = AsyncMock()  # type: ignore[method-assign]
    return h


def _wireRandomPath(
    handler: LLMMessageHandler,
    *,
    isReply: bool = False,
    threadSystem: str = "BASE SYSTEM",
) -> tuple[EnsuredMessage, contextlib.ExitStack]:
    """Mock the handleRandomMessage-specific leaves and return an :class:`EnsuredMessage`.

    ``EnsuredMessage`` uses ``__slots__``, so its methods cannot be overridden
    on an instance. The ``toModelMessageList`` method is therefore patched at
    class level inside an :class:`contextlib.ExitStack`; the caller must keep the
    stack entered (``with stack:``) for the duration of the handler call.

    Args:
        handler: The live handler fixture.
        isReply: If True, set ``replyId`` and mock ``getThreadByMessageForLLM``
            so the thread assembly path runs.
        threadSystem: Content of the leading system message returned by the
            mocked ``getThreadByMessageForLLM`` (thread path only).

    Returns:
        A ``(em, stack)`` pair: the :class:`EnsuredMessage` ready for the
        random-answer path, and an entered :class:`contextlib.ExitStack` that
        restores the patched methods on exit.
    """
    em = _liveEnsuredMessage(isReply=isReply)
    stack = contextlib.ExitStack()
    stack.enter_context(patch.object(EnsuredMessage, "toModelMessageList", AsyncMock(return_value=[])))
    if isReply:
        handler.getThreadByMessageForLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=[ModelMessage(role="system", content=threadSystem)]
        )
    return em, stack


def _wireReplyPath(
    handler: LLMMessageHandler, *, threadSystem: str = "BASE SYSTEM"
) -> tuple[EnsuredMessage, contextlib.ExitStack]:
    """Mock the handleReply-specific leaves and return a reply :class:`EnsuredMessage`.

    ``updateMediaContent`` and ``getEnsuredRepliedToMessage`` are patched at
    class level (see :func:`_wireRandomPath` for the ``__slots__`` rationale).

    Args:
        handler: The live handler fixture.
        threadSystem: Content of the leading system message returned by the
            mocked ``getThreadByMessageForLLM``.

    Returns:
        A ``(em, stack)`` pair: the reply :class:`EnsuredMessage` (configured so
        ``isReplyToMyMessage`` is True) and an entered
        :class:`contextlib.ExitStack`.
    """
    em = _liveEnsuredMessage(isReply=True)
    replied = _liveEnsuredMessage(senderId=999, senderName="Bot")
    stack = contextlib.ExitStack()
    stack.enter_context(patch.object(EnsuredMessage, "getEnsuredRepliedToMessage", Mock(return_value=replied)))
    stack.enter_context(patch.object(EnsuredMessage, "updateMediaContent", AsyncMock(return_value=None)))
    handler.getThreadByMessageForLLM = AsyncMock(  # type: ignore[method-assign]
        return_value=[ModelMessage(role="system", content=threadSystem)]
    )
    handler.getBotId = AsyncMock(return_value=999)  # type: ignore[method-assign]
    return em, stack


def _wireMentionPath(handler: LLMMessageHandler) -> tuple[EnsuredMessage, contextlib.ExitStack]:
    """Mock the handleMention-specific leaves and return an :class:`EnsuredMessage`.

    ``toModelMessage`` is patched at class level (see :func:`_wireRandomPath`
    for the ``__slots__`` rationale).

    Args:
        handler: The live handler fixture.

    Returns:
        A ``(em, stack)`` pair: the :class:`EnsuredMessage` that
        ``checkEMMentionsMe`` reports as mentioning the bot, and an entered
        :class:`contextlib.ExitStack`.
    """
    em = _liveEnsuredMessage()
    handler.checkEMMentionsMe = AsyncMock(  # type: ignore[method-assign]
        return_value=MentionCheckResult(byName=(0, 4), restText="hello there")
    )
    stack = contextlib.ExitStack()
    stack.enter_context(
        patch.object(
            EnsuredMessage, "toModelMessage", AsyncMock(return_value=ModelMessage(role="user", content="hello there"))
        )
    )
    return em, stack


# ---------------------------------------------------------------------------
# Tests: RANDOM_ANSWER_PROMPT wiring + <skip> sentinel
# ---------------------------------------------------------------------------


class TestRandomAnswerPromptAndSkipSentinel:
    """Pin the RANDOM_ANSWER_PROMPT wiring and the ``<skip>`` abstention sentinel.

    Covers the four behaviours introduced by the random-answer-context feature:

    * ``RANDOM_ANSWER_PROMPT`` is appended to the system message inside
      ``handleRandomMessage`` (both thread and non-thread assembly paths) and is
      NOT appended inside ``handleReply`` / ``handleMention``.
    * ``_sendLLMChatMessage`` returns ``LLMReplyOutcome.SKIPPED_BY_MODEL`` when
      the model returns the ``<skip>`` sentinel (plain or JSON-wrapped), sends
      nothing, and never triggers image generation.
    * The return-type change from ``bool`` to ``LLMReplyOutcome`` does not
      break the ``handleReply`` / ``handleMention`` / ``handleRandomMessage``
      call sites on a normal answer.
    """

    async def testRandomAnswerPromptAppendedToSystemMessageNonThreadPath(self, liveHandler: LLMMessageHandler) -> None:
        """Non-thread random answer: system message includes the prompt fragment.

        Args:
            liveHandler: Live handler fixture.
        """
        generate, captured = _captureGenerate("Привет!")
        liveHandler.llmService.generateTextViaLLM = generate  # type: ignore[method-assign]
        em, stack = _wireRandomPath(liveHandler, isReply=False)

        with stack, patch("random.random", return_value=0.0):
            result = await liveHandler.handleRandomMessage(em, Mock())

        assert result is True
        messages = captured["messages"]
        assert RANDOM_PROMPT_MARKER in messages[0].content

    async def testRandomAnswerPromptAppendedToSystemMessageThreadPath(self, liveHandler: LLMMessageHandler) -> None:
        """Thread random answer: prompt is appended to the thread's system message.

        Args:
            liveHandler: Live handler fixture.
        """
        generate, captured = _captureGenerate("ok")
        liveHandler.llmService.generateTextViaLLM = generate  # type: ignore[method-assign]
        em, stack = _wireRandomPath(liveHandler, isReply=True, threadSystem="BASE SYSTEM")

        with stack, patch("random.random", return_value=0.0):
            result = await liveHandler.handleRandomMessage(em, Mock())

        assert result is True
        messages = captured["messages"]
        assert "BASE SYSTEM" in messages[0].content
        assert RANDOM_PROMPT_MARKER in messages[0].content

    async def testRandomAnswerPromptNotAppendedToReply(self, liveHandler: LLMMessageHandler) -> None:
        """handleReply must NOT receive the random-answer fragment.

        Args:
            liveHandler: Live handler fixture.
        """
        generate, captured = _captureGenerate("hi")
        liveHandler.llmService.generateTextViaLLM = generate  # type: ignore[method-assign]
        em, stack = _wireReplyPath(liveHandler, threadSystem="BASE SYSTEM")

        with stack:
            result = await liveHandler.handleReply(em, Mock())

        assert result is True
        messages = captured["messages"]
        assert RANDOM_PROMPT_MARKER not in messages[0].content

    async def testReplyFallbackInjectsMemoriesBlock(self, liveHandler: LLMMessageHandler) -> None:
        """handleReply fallback (empty thread) still injects the memories block.

        Regression for Fix 3: when ``getThreadByMessageForLLM`` returns ``[]``
        (root message not in DB), ``handleReply`` rebuilds the system message
        from ``CHAT_PROMPT + CHAT_PROMPT_SUFFIX`` and appends the bot/user
        messages directly. That fallback must ALSO inject the ``<user-memories>``
        block — otherwise a reply-to-bot in this error path is processed
        without memory context. Mirrors site 2 (handleMention).

        ``_buildMemoriesBlock`` is stubbed to a known block so the test
        isolates the injection wiring (not the build logic).

        Args:
            liveHandler: Live handler fixture.
        """
        generate, captured = _captureGenerate("hi")
        liveHandler.llmService.generateTextViaLLM = generate  # type: ignore[method-assign]
        em = _liveEnsuredMessage(isReply=True)
        replied = _liveEnsuredMessage(senderId=999, senderName="Bot")
        memoriesBlock = "<user-memories>FALLBACK-MEMORIES</user-memories>"
        liveHandler.getThreadByMessageForLLM = AsyncMock(return_value=[])  # type: ignore[method-assign]
        liveHandler.getBotId = AsyncMock(return_value=999)  # type: ignore[method-assign]
        liveHandler._buildMemoriesBlock = AsyncMock(return_value=memoriesBlock)  # type: ignore[method-assign]

        with (
            patch.object(EnsuredMessage, "getEnsuredRepliedToMessage", Mock(return_value=replied)),
            patch.object(EnsuredMessage, "updateMediaContent", AsyncMock(return_value=None)),
            patch.object(
                EnsuredMessage,
                "toModelMessage",
                AsyncMock(return_value=ModelMessage(role="user", content="x")),
            ),
        ):
            result = await liveHandler.handleReply(em, Mock())

        assert result is True
        messages = captured["messages"]
        assert "FALLBACK-MEMORIES" in messages[0].content
        liveHandler._buildMemoriesBlock.assert_awaited_once()  # type: ignore[attr-defined]
        # The fallback resolves the target user from the incoming-message sender
        # (the message this turn is about), not the replied-to bot message.
        callArgs = liveHandler._buildMemoriesBlock.call_args  # type: ignore[attr-defined]
        assert callArgs.args[0] == em.recipient.id
        assert callArgs.args[1] == em.sender.id

    async def testRandomAnswerPromptNotAppendedToMention(self, liveHandler: LLMMessageHandler) -> None:
        """handleMention must NOT receive the random-answer fragment.

        Args:
            liveHandler: Live handler fixture.
        """
        generate, captured = _captureGenerate("hi")
        liveHandler.llmService.generateTextViaLLM = generate  # type: ignore[method-assign]
        em, stack = _wireMentionPath(liveHandler)

        with stack:
            result = await liveHandler.handleMention(em, Mock())

        assert result is True
        messages = captured["messages"]
        assert RANDOM_PROMPT_MARKER not in messages[0].content

    async def testSkipMarkerReturnsSkippedByModelAndNoMessageSent(self, liveHandler: LLMMessageHandler) -> None:
        """Plain ``<skip>`` → ``SKIPPED_BY_MODEL`` and ``sendMessage`` untouched.

        Args:
            liveHandler: Live handler fixture.
        """
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("<skip>")
        )
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="system", content="sys")]
        typingManager = AsyncMock()

        outcome = await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        assert outcome == LLMReplyOutcome.SKIPPED_BY_MODEL
        liveHandler.sendMessage.assert_not_awaited()  # type: ignore[attr-defined]
        liveHandler.llmService.generateImage.assert_not_awaited()  # type: ignore[attr-defined]

    async def testSkipMarkerAfterJsonUnwrap(self, liveHandler: LLMMessageHandler) -> None:
        """JSON-wrapped ``{"text": "<skip>"}`` abstains after the unwrap branch.

        Requires ``LLM_MESSAGE_FORMAT != JSON`` so the JSON-unwrap branch runs;
        the ``liveHandler`` fixture defaults it to ``"text"``.

        Args:
            liveHandler: Live handler fixture.
        """
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult('`{"text": "<skip>"}`')
        )
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="system", content="sys")]
        typingManager = AsyncMock()

        outcome = await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        assert outcome == LLMReplyOutcome.SKIPPED_BY_MODEL
        liveHandler.sendMessage.assert_not_awaited()  # type: ignore[attr-defined]
        liveHandler.llmService.generateImage.assert_not_awaited()  # type: ignore[attr-defined]

    async def testNormalRandomAnswerStillWorks(self, liveHandler: LLMMessageHandler) -> None:
        """A normal random answer is sent and ``handleRandomMessage`` returns True.

        Args:
            liveHandler: Live handler fixture.
        """
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("Привет!")
        )
        em, stack = _wireRandomPath(liveHandler, isReply=False)

        with stack, patch("random.random", return_value=0.0):
            result = await liveHandler.handleRandomMessage(em, Mock())

        assert result is True
        liveHandler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.parametrize("path", ["reply", "mention"])
    async def testExplicitAddressPathsStillSendOnNormalAnswer(self, liveHandler: LLMMessageHandler, path: str) -> None:
        """handleReply/handleMention still send on a normal answer (return-type guard).

        The ``_sendLLMChatMessage`` return type changed from ``bool`` to
        ``LLMReplyOutcome``; both explicit-address paths must still treat a
        normal answer as success and return ``True``.

        Args:
            liveHandler: Live handler fixture.
            path: ``"reply"`` or ``"mention"``.
        """
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("sure")
        )
        if path == "reply":
            em, stack = _wireReplyPath(liveHandler)
            with stack:
                result = await liveHandler.handleReply(em, Mock())
        else:
            em, stack = _wireMentionPath(liveHandler)
            with stack:
                result = await liveHandler.handleMention(em, Mock())

        assert result is True
        liveHandler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Tests: <media-description> extraction in _sendLLMChatMessage
# ---------------------------------------------------------------------------


class TestMediaDescriptionExtraction:
    """Pin the ``<media-description>`` tag extraction in ``_sendLLMChatMessage``.

    Covers the extraction block (lines ~345-355 of
    ``internal/bot/common/handlers/llm_messages.py``) that splits an LLM
    response into an image prompt (inside the tag) and the surrounding message
    text. The block is gated on ``LLM_MESSAGE_FORMAT != JSON`` and on the
    trimmed text starting with ``<media-description>`` or ending with
    ``</media-description>`` (pure-middle tags are intentionally excluded).

    All tests call ``_sendLLMChatMessage`` directly (not via the public
    ``handle*`` methods) so only the extraction + image-gen + send logic is
    exercised. Positive tests assert on BOTH ``generateImage`` (the prompt) and
    ``sendMessage`` (the ``messageText`` kwarg). Negative tests assert
    ``generateImage`` was never awaited.

    Important ordering note: the ``<skip>``/empty-text abstention sentinel runs
    BEFORE the image-gen branch, but is gated on ``imagePrompt is None``. So a
    tag-only response (no surrounding text) leaves ``lmRetText == ""`` yet does
    NOT trip the sentinel — the image request takes precedence and is generated.
    See :meth:`testTagOnlyGeneratesImage`.
    """

    async def testTagAtStartAndTrailingTextExtracts(self, liveHandler: LLMMessageHandler) -> None:
        """Tag at start + trailing text → image from tag, message from trailing.

        ``<media-description>foo</media-description>bar`` → ``generateImage``
        called with ``"foo"``, ``sendMessage`` called with ``messageText="bar"``.

        This is the original bug regression: before the fix, the regex without
        the ``$`` anchor produced ``messageText=""`` (trailing text silently
        discarded). With the fix, group(3) captures ``"bar"``.

        Args:
            liveHandler: Live handler fixture.
        """
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("<media-description>foo</media-description>bar")
        )
        liveHandler.llmService.generateImage = AsyncMock(return_value=_imageRunResult())  # type: ignore[method-assign]
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="user", content="test")]
        typingManager = AsyncMock()

        outcome = await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        assert outcome == LLMReplyOutcome.SENT
        liveHandler.llmService.generateImage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.llmService.generateImage.call_args.args[0] == "foo"  # type: ignore[attr-defined]
        liveHandler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.sendMessage.call_args.kwargs["messageText"] == "bar"  # type: ignore[attr-defined]

    async def testLeadingTextAndTagAtEndExtracts(self, liveHandler: LLMMessageHandler) -> None:
        """Leading text + tag at end → image from tag, message from leading text.

        ``baz<media-description>foo</media-description>`` → ``generateImage``
        called with ``"foo"``, ``sendMessage`` called with ``messageText="baz"``.

        Args:
            liveHandler: Live handler fixture.
        """
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("baz<media-description>foo</media-description>")
        )
        liveHandler.llmService.generateImage = AsyncMock(return_value=_imageRunResult())  # type: ignore[method-assign]
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="user", content="test")]
        typingManager = AsyncMock()

        outcome = await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        assert outcome == LLMReplyOutcome.SENT
        liveHandler.llmService.generateImage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.llmService.generateImage.call_args.args[0] == "foo"  # type: ignore[attr-defined]
        liveHandler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.sendMessage.call_args.kwargs["messageText"] == "baz"  # type: ignore[attr-defined]

    async def testTagOnlyGeneratesImage(self, liveHandler: LLMMessageHandler) -> None:
        """Tag-only response (no surrounding text) → image generated and sent.

        ``<media-description>foo</media-description>`` → extraction sets
        ``imagePrompt="foo"`` and ``lmRetText=""``. The abstention sentinel
        (``lmRetText in ("<skip>", "")``) is gated on ``imagePrompt is None``,
        so it does NOT fire here: a tag-only request is an image request, not
        an abstention. ``generateImage`` is awaited with ``"foo"``, the photo
        is sent via ``sendMessage``, and the outcome is ``SENT``.

        This pins the corrected interaction: the sentinel is skipped whenever
        the model produced an image request, even when the caption text is
        empty — the image IS the response. (Before the fix, the sentinel fired
        on the empty caption and silently dropped the requested image.)

        Args:
            liveHandler: Live handler fixture.
        """
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("<media-description>foo</media-description>")
        )
        liveHandler.llmService.generateImage = AsyncMock(return_value=_imageRunResult())  # type: ignore[method-assign]
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="user", content="test")]
        typingManager = AsyncMock()

        outcome = await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        assert outcome == LLMReplyOutcome.SENT
        liveHandler.llmService.generateImage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.llmService.generateImage.call_args.args[0] == "foo"  # type: ignore[attr-defined]
        liveHandler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.sendMessage.call_args.kwargs["messageText"] == ""  # type: ignore[attr-defined]

    async def testBacktickAndWhitespaceWrappedExtracts(self, liveHandler: LLMMessageHandler) -> None:
        """Backtick/whitespace-wrapped tag → strips wrapper, extracts content.

        Input ``"`  <media-description>foo</media-description>bar  `"`` → the
        ``.strip().strip("`").strip()`` chain removes the wrapper, then the
        regex extracts ``imagePrompt="foo"`` and ``messageText="bar"``.

        Args:
            liveHandler: Live handler fixture.
        """
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("`  <media-description>foo</media-description>bar  `")
        )
        liveHandler.llmService.generateImage = AsyncMock(return_value=_imageRunResult())  # type: ignore[method-assign]
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="user", content="test")]
        typingManager = AsyncMock()

        outcome = await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        assert outcome == LLMReplyOutcome.SENT
        liveHandler.llmService.generateImage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.llmService.generateImage.call_args.args[0] == "foo"  # type: ignore[attr-defined]
        liveHandler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.sendMessage.call_args.kwargs["messageText"] == "bar"  # type: ignore[attr-defined]

    async def testMultilineContentExtractsWithDotall(self, liveHandler: LLMMessageHandler) -> None:
        """Multi-line content inside the tag is captured (DOTALL flag).

        ``<media-description>line1\\nline2</media-description>text`` → the
        regex uses ``re.DOTALL`` so ``.`` matches newlines, yielding
        ``imagePrompt="line1\\nline2"`` and ``messageText="text"``.

        Args:
            liveHandler: Live handler fixture.
        """
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("<media-description>line1\nline2</media-description>text")
        )
        liveHandler.llmService.generateImage = AsyncMock(return_value=_imageRunResult())  # type: ignore[method-assign]
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="user", content="test")]
        typingManager = AsyncMock()

        outcome = await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        assert outcome == LLMReplyOutcome.SENT
        liveHandler.llmService.generateImage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.llmService.generateImage.call_args.args[0] == "line1\nline2"  # type: ignore[attr-defined]
        liveHandler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.sendMessage.call_args.kwargs["messageText"] == "text"  # type: ignore[attr-defined]

    async def testTagInMiddleDoesNotExtract(self, liveHandler: LLMMessageHandler) -> None:
        """Tag in the middle (text on both sides) → no extraction (intentional).

        ``text<media-description>foo</media-description>text`` → the gate
        (``startswith OR endswith``) is False, so no extraction runs. The full
        original text is sent as the message and ``generateImage`` is never
        called. This is INTENTIONAL: pure-middle tags are excluded by design.

        Args:
            liveHandler: Live handler fixture.
        """
        fullText = "text<media-description>foo</media-description>text"
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult(fullText)
        )
        liveHandler.llmService.generateImage = AsyncMock(return_value=_imageRunResult())  # type: ignore[method-assign]
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="user", content="test")]
        typingManager = AsyncMock()

        outcome = await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        assert outcome == LLMReplyOutcome.SENT
        liveHandler.llmService.generateImage.assert_not_awaited()  # type: ignore[attr-defined]
        liveHandler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.sendMessage.call_args.kwargs["messageText"] == fullText  # type: ignore[attr-defined]

    async def testJsonFormatModeDoesNotExtract(self, liveHandler: LLMMessageHandler) -> None:
        """``LLM_MESSAGE_FORMAT = JSON`` → entire extraction block skipped.

        Even with a tag at the start, ``generateImage`` is never called because
        the extraction block is gated on ``llmMessageFormat != JSON``. The full
        text is sent as-is. This is INTENTIONAL.

        Args:
            liveHandler: Live handler fixture.
        """
        fullText = "<media-description>foo</media-description>bar"
        liveHandler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_fullChatSettings(llmMessageFormat="json")
        )
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult(fullText)
        )
        liveHandler.llmService.generateImage = AsyncMock(return_value=_imageRunResult())  # type: ignore[method-assign]
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="user", content="test")]
        typingManager = AsyncMock()

        outcome = await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        assert outcome == LLMReplyOutcome.SENT
        liveHandler.llmService.generateImage.assert_not_awaited()  # type: ignore[attr-defined]
        liveHandler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.sendMessage.call_args.kwargs["messageText"] == fullText  # type: ignore[attr-defined]

    async def testNoTagPresentDoesNotExtract(self, liveHandler: LLMMessageHandler) -> None:
        """Plain text with no tag → no extraction, message sent as-is.

        ``hello world`` → no extraction, ``generateImage`` never called,
        ``sendMessage`` called with ``messageText="hello world"``.

        Args:
            liveHandler: Live handler fixture.
        """
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("hello world")
        )
        liveHandler.llmService.generateImage = AsyncMock(return_value=_imageRunResult())  # type: ignore[method-assign]
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="user", content="test")]
        typingManager = AsyncMock()

        outcome = await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        assert outcome == LLMReplyOutcome.SENT
        liveHandler.llmService.generateImage.assert_not_awaited()  # type: ignore[attr-defined]
        liveHandler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.sendMessage.call_args.kwargs["messageText"] == "hello world"  # type: ignore[attr-defined]

    async def testTwoTagsExtractsOnlyFirst(self, liveHandler: LLMMessageHandler) -> None:
        """Two tags with first at start → only the first is extracted (intentional).

        ``<media-description>foo</media-description>middle<media-description>bar</media-description>``
        → the gate passes (``startswith``). The non-greedy ``group(2)`` stops at
        the FIRST ``</media-description>``, so ``imagePrompt="foo"``. The
        remaining text ``"middle<media-description>bar</media-description>"``
        (second tag survives as literal text) is sent as the message. Only ONE
        tag is handled per message — INTENTIONAL per the user.

        Args:
            liveHandler: Live handler fixture.
        """
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult(
                "<media-description>foo</media-description>middle<media-description>bar</media-description>"
            )
        )
        liveHandler.llmService.generateImage = AsyncMock(return_value=_imageRunResult())  # type: ignore[method-assign]
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="user", content="test")]
        typingManager = AsyncMock()

        outcome = await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        assert outcome == LLMReplyOutcome.SENT
        liveHandler.llmService.generateImage.assert_awaited_once()  # type: ignore[attr-defined]
        assert liveHandler.llmService.generateImage.call_args.args[0] == "foo"  # type: ignore[attr-defined]
        liveHandler.sendMessage.assert_awaited_once()  # type: ignore[attr-defined]
        assert (
            liveHandler.sendMessage.call_args.kwargs["messageText"]  # type: ignore[attr-defined]
            == "middle<media-description>bar</media-description>"
        )


# ---------------------------------------------------------------------------
# Tests: D3 gating — DELETE_MEMORY never exposed at chat time
# ---------------------------------------------------------------------------


class TestD3DeleteMemoryGating:
    """D3 regression: ``DELETE_MEMORY`` is never exposed at chat time.

    Pins the Fix 1 restructuring in ``_sendLLMChatMessage``: the
    ``DELETE_MEMORY: False`` override must apply regardless of the
    ``ALLOW_SANDBOX`` setting. Before the fix, the whole ``useTools``
    dict-construction block was guarded by
    ``if useTools and not all([useSandbox]):``, so when ``ALLOW_SANDBOX=true``
    the block was skipped entirely — ``useTools`` stayed the plain bool
    ``True`` and ``_resolveTools`` returned ALL registered tools, including
    ``DELETE_MEMORY`` (violating D3: delete is refinement-only; plan §8.3).

    Each test registers ``DELETE_MEMORY`` and a sandbox tool on the handler's
    ``LLMService`` singleton, drives ``_sendLLMChatMessage`` with a given
    ``(USE_TOOLS, ALLOW_SANDBOX)`` combo, captures the ``useTools`` value
    passed to ``generateTextViaLLM``, resolves it via ``_resolveTools``, and
    asserts ``DELETE_MEMORY`` is never among the resolved tool names.
    """

    @pytest.mark.parametrize(
        ("useToolsSetting", "allowSandboxSetting"),
        [
            (True, True),  # the case that was broken before Fix 1
            (True, False),
            (False, True),
            (False, False),
        ],
    )
    async def test_deleteMemoryNeverResolvedAtChatTime(
        self,
        liveHandler: LLMMessageHandler,
        useToolsSetting: bool,
        allowSandboxSetting: bool,
    ) -> None:
        """``DELETE_MEMORY`` absent from resolved tools for all 4 setting combos.

        Args:
            liveHandler: Live handler fixture.
            useToolsSetting: Value for ``USE_TOOLS`` chat setting.
            allowSandboxSetting: Value for ``ALLOW_SANDBOX`` chat setting.
        """
        # Register DELETE_MEMORY + a sandbox tool on the singleton so the
        # assertion is meaningful (otherwise DELETE_MEMORY's absence is
        # trivially true because nothing is registered).
        liveHandler.llmService.registerTool(
            name=ToolName.DELETE_MEMORY,
            description="delete memory (refinement-only)",
            parameters=[],
            handler=AsyncMock(),
        )
        liveHandler.llmService.registerTool(
            name=ToolName.RUN_PYTHON,
            description="run python",
            parameters=[],
            handler=AsyncMock(),
        )

        settings = _fullChatSettings()
        settings[ChatSettingsKey.USE_TOOLS] = ChatSettingsValue("true" if useToolsSetting else "false")
        settings[ChatSettingsKey.ALLOW_SANDBOX] = ChatSettingsValue("true" if allowSandboxSetting else "false")
        liveHandler.getChatSettings = AsyncMock(return_value=settings)  # type: ignore[method-assign]

        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("ok")
        )
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="system", content="sys")]
        typingManager = AsyncMock()

        await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        capturedUseTools = liveHandler.llmService.generateTextViaLLM.call_args.kwargs[  # type: ignore[attr-defined]
            "useTools"
        ]
        resolved = liveHandler.llmService._resolveTools(capturedUseTools)  # type: ignore[attr-defined]
        resolvedNames = {t.name for t in resolved}
        # D3: DELETE_MEMORY must never appear in chat-time tools, regardless of
        # the sandbox setting.
        assert ToolName.DELETE_MEMORY not in resolvedNames

        # Sanity: when USE_TOOLS=true the sandbox tool (RUN_PYTHON) is present
        # when ALLOW_SANDBOX=true, proving the fix does not over-disable
        # everything. The (True, True) combo is the one that was broken: before
        # Fix 1, ``useTools`` stayed a plain ``True`` and ALL tools (including
        # DELETE_MEMORY) were returned.
        if useToolsSetting:
            if allowSandboxSetting:
                assert ToolName.RUN_PYTHON in resolvedNames
            else:
                assert ToolName.RUN_PYTHON not in resolvedNames
        else:
            # USE_TOOLS=false → no tools at all.
            assert resolvedNames == set()


class TestMemoryInjectionToolGating:
    """Phase 3a: ``MEMORY_INJECTION_ENABLED`` gates ``ADD_MEMORY`` / ``SEARCH_MEMORIES``.

    Pins the useTools gate added in ``_sendLLMChatMessage`` (plan §13 / §11.1):
    when the chat-time ``MEMORY_INJECTION_ENABLED`` setting is off, both
    ``ADD_MEMORY`` and ``SEARCH_MEMORIES`` are explicitly disabled in the
    per-call ``useTools`` dict so the memory tools don't appear before the
    feature is opted in. When the setting is on, both are left to the wildcard
    (available). ``DELETE_MEMORY`` stays off regardless (D3 — covered by
    :class:`TestD3DeleteMemoryGating`).
    """

    @pytest.mark.parametrize(
        "injectionEnabled",
        [True, False],
    )
    async def test_addAndSearchMemoriesGatedOnInjectionFlag(
        self,
        liveHandler: LLMMessageHandler,
        injectionEnabled: bool,
    ) -> None:
        """``ADD_MEMORY``/``SEARCH_MEMORIES`` resolved iff ``MEMORY_INJECTION_ENABLED`` is on.

        Registers all three memory tools on the singleton (so absence is
        meaningful, not trivial), drives ``_sendLLMChatMessage`` with
        ``USE_TOOLS=true``, captures the ``useTools`` kwarg, and resolves it
        via ``_resolveTools``.

        Args:
            liveHandler: Live handler fixture.
            injectionEnabled: Value for ``MEMORY_INJECTION_ENABLED``.
        """
        # Register all three memory tools so the assertion is meaningful.
        for name in (ToolName.ADD_MEMORY, ToolName.SEARCH_MEMORIES, ToolName.DELETE_MEMORY):
            liveHandler.llmService.registerTool(
                name=name,
                description=f"memory tool {name}",
                parameters=[],
                handler=AsyncMock(),
            )

        settings = _fullChatSettings()
        settings[ChatSettingsKey.USE_TOOLS] = ChatSettingsValue("true")
        settings[ChatSettingsKey.ALLOW_SANDBOX] = ChatSettingsValue("false")
        settings[ChatSettingsKey.MEMORY_INJECTION_ENABLED] = ChatSettingsValue("true" if injectionEnabled else "false")
        liveHandler.getChatSettings = AsyncMock(return_value=settings)  # type: ignore[method-assign]

        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("ok")
        )
        em = _liveEnsuredMessage()
        messagesHistory = [ModelMessage(role="system", content="sys")]
        typingManager = AsyncMock()

        await liveHandler._sendLLMChatMessage(em, messagesHistory, typingManager=typingManager)

        capturedUseTools = liveHandler.llmService.generateTextViaLLM.call_args.kwargs[  # type: ignore[attr-defined]
            "useTools"
        ]
        assert isinstance(capturedUseTools, dict)
        resolved = liveHandler.llmService._resolveTools(capturedUseTools)  # type: ignore[attr-defined]
        resolvedNames = {t.name for t in resolved}

        # DELETE_MEMORY is always hidden at chat time (D3), regardless of the
        # injection setting.
        assert ToolName.DELETE_MEMORY not in resolvedNames

        if injectionEnabled:
            # Both memory tools fall through to the wildcard (available).
            assert ToolName.ADD_MEMORY in resolvedNames
            assert ToolName.SEARCH_MEMORIES in resolvedNames
        else:
            # The gate explicitly disables both.
            assert ToolName.ADD_MEMORY not in resolvedNames
            assert ToolName.SEARCH_MEMORIES not in resolvedNames
            # And the raw useTools dict carries the explicit False overrides.
            assert capturedUseTools.get(ToolName.ADD_MEMORY) is False
            assert capturedUseTools.get(ToolName.SEARCH_MEMORIES) is False


class TestMemoriesBlockInjection:
    """Phase 3a: the ``<user-memories>`` block lands in the system message at each site.

    Integration coverage for plan §9.2 sites 2 (``handleMention``) and 3
    (``handleRandomMessage`` non-thread branch). Site 1
    (``getThreadByMessageForLLM``) is covered by the ``_buildMemoriesBlock`` /
    ``_injectMemoriesBlock`` unit tests in ``test_base.py`` (the helper logic
    is identical; only the call site differs). ``_buildMemoriesBlock`` is
    stubbed to return a sentinel block so no DB seeding is required.
    """

    async def test_handleMention_appendsMemoriesBlockToSystemMessage(self, liveHandler: LLMMessageHandler) -> None:
        """``handleMention`` appends the block to ``reqMessages[0].content`` when enabled.

        Stubs ``_buildMemoriesBlock`` to return a known sentinel, drives
        ``handleMention`` (via ``_wireMentionPath``), captures the messages
        passed to ``generateTextViaLLM``, and asserts the leading system
        message contains the sentinel.

        Args:
            liveHandler: Live handler fixture.
        """
        settings = _fullChatSettings()
        settings[ChatSettingsKey.MEMORY_INJECTION_ENABLED] = ChatSettingsValue("true")
        liveHandler.getChatSettings = AsyncMock(return_value=settings)  # type: ignore[method-assign]
        liveHandler._buildMemoriesBlock = AsyncMock(  # type: ignore[method-assign]
            return_value="<user-memories>MENTION_SENTINEL</user-memories>"
        )
        generate, captured = _captureGenerate("ok")
        liveHandler.llmService.generateTextViaLLM = generate  # type: ignore[method-assign]

        em, stack = _wireMentionPath(liveHandler)
        with stack:
            await liveHandler.handleMention(em, updateObj=Mock())

        msgs = captured["messages"]
        assert msgs[0].role == "system"
        assert "<user-memories>MENTION_SENTINEL</user-memories>" in msgs[0].content
        liveHandler._buildMemoriesBlock.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_handleRandomMessageNonThread_appendsMemoriesBlockToSystemMessage(
        self, liveHandler: LLMMessageHandler
    ) -> None:
        """``handleRandomMessage`` non-thread branch appends the block to the system message.

        Uses ``_wireRandomPath(isReply=False)`` so the non-thread branch runs
        (the thread branch already gets the block via site 1).

        Args:
            liveHandler: Live handler fixture.
        """
        settings = _fullChatSettings()
        settings[ChatSettingsKey.MEMORY_INJECTION_ENABLED] = ChatSettingsValue("true")
        liveHandler.getChatSettings = AsyncMock(return_value=settings)  # type: ignore[method-assign]
        liveHandler._buildMemoriesBlock = AsyncMock(  # type: ignore[method-assign]
            return_value="<user-memories>RANDOM_SENTINEL</user-memories>"
        )
        generate, captured = _captureGenerate("ok")
        liveHandler.llmService.generateTextViaLLM = generate  # type: ignore[method-assign]

        em, stack = _wireRandomPath(liveHandler, isReply=False)
        with stack:
            await liveHandler.handleRandomMessage(em, updateObj=Mock())

        msgs = captured["messages"]
        assert msgs[0].role == "system"
        assert "<user-memories>RANDOM_SENTINEL</user-memories>" in msgs[0].content
        liveHandler._buildMemoriesBlock.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_handleMention_doesNotInject_whenInjectionDisabled(self, liveHandler: LLMMessageHandler) -> None:
        """With ``MEMORY_INJECTION_ENABLED=false`` the system message has no block.

        ``_buildMemoriesBlock`` returns ``None`` (the disabled short-circuit),
        so ``_injectMemoriesBlock`` is a no-op and the system message keeps its
        base content. Pins the negative path so the block isn't accidentally
        injected when the feature is off.

        Args:
            liveHandler: Live handler fixture.
        """
        # _fullChatSettings already has MEMORY_INJECTION_ENABLED=false.
        liveHandler._buildMemoriesBlock = AsyncMock(return_value=None)  # type: ignore[method-assign]
        generate, captured = _captureGenerate("ok")
        liveHandler.llmService.generateTextViaLLM = generate  # type: ignore[method-assign]

        em, stack = _wireMentionPath(liveHandler)
        with stack:
            await liveHandler.handleMention(em, updateObj=Mock())

        msgs = captured["messages"]
        assert "<user-memories>" not in msgs[0].content
