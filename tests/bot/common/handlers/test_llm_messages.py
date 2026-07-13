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
import json
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
    MessageType,
)
from internal.bot.models.message_metadata import CondensingDict, mergeCondensingDicts
from internal.database.models import ChatMessageDict, MessageCategory
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
        # that exercise the gate override MEMORY_ENABLED inline by
        # building a settings dict with it set to "true" directly.
        ChatSettingsKey.MEMORY_ENABLED: ChatSettingsValue("false"),
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
    """Phase 3a: ``MEMORY_ENABLED`` gates ``ADD_MEMORY`` / ``SEARCH_MEMORIES``.

    Pins the useTools gate added in ``_sendLLMChatMessage`` (plan §13 / §11.1):
    when the chat-time ``MEMORY_ENABLED`` setting is off, both
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
        """``ADD_MEMORY``/``SEARCH_MEMORIES`` resolved iff ``MEMORY_ENABLED`` is on.

        Registers all three memory tools on the singleton (so absence is
        meaningful, not trivial), drives ``_sendLLMChatMessage`` with
        ``USE_TOOLS=true``, captures the ``useTools`` kwarg, and resolves it
        via ``_resolveTools``.

        Args:
            liveHandler: Live handler fixture.
            injectionEnabled: Value for ``MEMORY_ENABLED``.
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
        settings[ChatSettingsKey.MEMORY_ENABLED] = ChatSettingsValue("true" if injectionEnabled else "false")
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


# ---------------------------------------------------------------------------
# NOTE: handler-level ``<user-memories>`` system-message block injection
# (the former ``TestMemoriesBlockInjection`` class) was removed. Memory
# injection moved to :meth:`MessagePreprocessorHandler.injectMemories`
# (pre-arrival), which writes compact memory IDs into ``metadata["memories"]``;
# the per-message renderer (:meth:`formatForLLM`) resolves them lazily via
# ``cache.getMemoriesByIds`` into a structured ``userMemories`` JSON key. The
# old handler-side ``_buildMemoriesBlock`` / ``_injectMemoriesBlock`` methods
# no longer exist (see the matching note in ``test_base.py``). The handler
# message-assembly paths themselves (handleMention / handleRandomMessage /
# handleReply) stay covered by :class:`TestRandomAnswerPromptAndSkipSentinel`
# and :class:`TestMediaDescriptionExtraction`.


# ---------------------------------------------------------------------------
# Tests: handleMention text-reply memory bypass (memory-compaction-v1 Phase 3b-i)
# ---------------------------------------------------------------------------


class TestHandleMentionCompactMemoryBypass:
    """Phase 3b-i: the ``handleMention`` text-reply bypass stores compact IDs in metadata.

    The text-message-reply branch of ``handleMention`` does NOT build its reply
    :class:`EnsuredMessage` via ``fromDBChatMessage``; it manually parses the
    stored reply's metadata JSON. Before Phase 3b-i the bypass tried to set
    memory content directly from the raw ``{"permanentIds": [...],
    "shortTermIds": [...]}`` ID dict — which ``formatForLLM`` would then render
    verbatim (garbage). The fix stores compact IDs in ``reply.metadata``
    directly (they are already in the stored metadata) and defers resolution to
    :meth:`formatForLLM` (lazy, via ``cache.getMemoriesByIds``).

    This test drives the REAL ``handleMention`` with ``MEMORY_ENABLED
    = true`` and a reply parent whose stored metadata carries compact IDs, then
    asserts on the live reply object's state. ``handleMention`` stores the
    compact IDs in ``reply.metadata`` and defers resolution to ``formatForLLM``
    (called via ``toModelMessage``, patched out here). So ``metadata["memories"]``
    preserves the compact IDs verbatim (no re-point / no mangling).
    """

    async def test_compactIdReply_resolvesLazilyViaFormatForLLM(self, liveHandler: LLMMessageHandler) -> None:
        """A compact-format stored reply preserves compact IDs; resolution is deferred to ``formatForLLM``.

        Args:
            liveHandler: Live handler fixture.
        """
        # Enable memory injection for the chat.
        settings = _fullChatSettings()
        settings[ChatSettingsKey.MEMORY_ENABLED] = ChatSettingsValue("true")
        liveHandler.getChatSettings = AsyncMock(return_value=settings)  # type: ignore[method-assign]

        # The incoming message mentions the bot and is a reply.
        em = _liveEnsuredMessage(isReply=True)
        liveHandler.checkEMMentionsMe = AsyncMock(  # type: ignore[method-assign]
            return_value=MentionCheckResult(byName=(0, 4), restText="hello there")
        )

        # Build the reply parent as a real EnsuredMessage with messageType=TEXT
        # (required to take the bypass branch).
        reply = EnsuredMessage(
            sender=MessageSender(id=7, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=-100, chatType=ChatType.GROUP),
            messageId=MessageId(55),
            date=datetime.datetime(2026, 5, 5, 11, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="an earlier message",
            messageType=MessageType.TEXT,
        )

        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(EnsuredMessage, "getEnsuredRepliedToMessage", Mock(return_value=reply)))
        # Patch toModelMessage at class level so the render doesn't touch the DB.
        stack.enter_context(
            patch.object(
                EnsuredMessage, "toModelMessage", AsyncMock(return_value=ModelMessage(role="user", content="x"))
            )
        )

        # Stored reply carries the COMPACT memory-ID format in metadata.
        compactMemories = {"permanentIds": ["a"], "shortTermIds": []}
        liveHandler.db.chatMessages.getChatMessageByMessageId = AsyncMock(  # type: ignore[method-assign]
            return_value={"metadata": json.dumps({"memories": compactMemories})}
        )
        # Stub cache resolves the compact ID -> content (keepId=False shape: no id).
        liveHandler.cache.getMemoriesByIds = AsyncMock(  # type: ignore[method-assign]
            return_value={"a": {"type": "fact", "content": "resolved perm fact", "tags": ["t"]}}
        )
        liveHandler.getBotId = AsyncMock(return_value=999)  # type: ignore[method-assign]
        liveHandler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("ok")
        )

        with stack:
            result = await liveHandler.handleMention(em, Mock())

        assert result is True

        # Phase 4: handleMention stores compact IDs in metadata for lazy
        # resolution by formatForLLM (toModelMessage is patched out here; the
        # resolution path is covered at the EnsuredMessage level). The
        # regression guard is: metadata preserves the compact IDs intact
        # (no re-point / no mangling).
        assert reply.metadata.get("memories") == compactMemories


# ---------------------------------------------------------------------------
# Tests: Phase 3b — handleRandomMessage condensing persists CondensingDict
# (Path B reshape: randomContext str → single CondensingDict with coverage)
# ---------------------------------------------------------------------------


def _makeContextRow(messageId: int, username: str, ts: float) -> ChatMessageDict:
    """Build a minimal ``ChatMessageDict`` for the condensing integration tests.

    Args:
        messageId: Message ID integer.
        username: Sender login.
        ts: Unix timestamp for the message date.

    Returns:
        A dict matching the ``ChatMessageDict`` shape with all required keys.
    """
    ret: ChatMessageDict = {
        "chat_id": -100,
        "message_id": MessageId(messageId),
        "date": datetime.datetime.fromtimestamp(ts, datetime.timezone.utc),
        "user_id": messageId,
        "reply_id": None,
        "thread_id": 0,
        "root_message_id": None,
        "message_text": f"msg-{messageId}",
        "message_type": "text",
        "message_category": MessageCategory.USER,
        "quote_text": None,
        "media_id": None,
        "created_at": datetime.datetime.fromtimestamp(ts, datetime.timezone.utc),
        "metadata": "{}",
        "markup": "",
        "media_group_id": None,
        "username": username,
        "full_name": username,
    }
    return ret


def _condensingChatSettings() -> ChatSettingsDict:
    """Build chat settings covering the condensing branch's reads.

    Extends :func:`_fullChatSettings` with the four condensing keys
    (``CHAT_MODEL``, ``CONDENSING_MODEL``, ``CONDENSING_PROMPT``,
    ``CONDENSING_SYSTEM_PROMPT``). Model values use real
    :class:`ChatSettingsValue` wrappers; ``ChatSettingsValue.toModel`` is
    patched at the test level to avoid hitting the real LLM manager.

    Returns:
        A complete :class:`ChatSettingsDict` including condensing keys.
    """
    base = _fullChatSettings()
    base[ChatSettingsKey.CHAT_MODEL] = ChatSettingsValue("dummy-chat-model")
    base[ChatSettingsKey.CONDENSING_MODEL] = ChatSettingsValue("dummy-condensing-model")
    base[ChatSettingsKey.CONDENSING_PROMPT] = ChatSettingsValue("condense prompt body")
    base[ChatSettingsKey.CONDENSING_SYSTEM_PROMPT] = ChatSettingsValue("condense sys body")
    return base


def _lightweightContextEM() -> EnsuredMessage:
    """Build a lightweight EnsuredMessage for the fromDBChatMessage mock.

    Has empty metadata (no ``randomContext``) so the context walk does not
    break early, and ``getMemoryIds()`` returns an empty set.

    Returns:
        A minimal :class:`EnsuredMessage`.
    """
    return EnsuredMessage(
        sender=MessageSender(id=1, name="ctx-user", username="@ctxuser"),
        recipient=MessageRecipient(id=-100, chatType=ChatType.GROUP),
        messageId=MessageId(999),
        date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText="context message",
    )


class TestHandleRandomMessageCondensing:
    """Phase 3b: ``handleRandomMessage`` persists ``randomContext`` as a CondensingDict.

    Drives the real ``handleRandomMessage`` through the condensing branch
    (``len(contextMessages) > MAX_RANDOM_CONTEXT_MESSAGES``) with
    ``condenseContext`` mocked to return deterministic
    ``(condensedRet, coverage)``. The new contract has ``condenseContext`` return a
    ``Dict[int, CondensingDict]`` for coverage; the handler merges its values via
    :func:`mergeCondensingDicts` and writes the result to
    ``metadata["randomContext"]``. When the coverage dict is empty, the
    ``if condencedDictMap:`` guard skips the write entirely (no randomContext).
    """

    @staticmethod
    def _wireCondensePath(
        handler: LLMMessageHandler,
        *,
        rows: list[ChatMessageDict],
        condensedRet: list[ModelMessage],
        coverage: dict[int, CondensingDict],
    ) -> tuple[EnsuredMessage, contextlib.ExitStack, AsyncMock]:
        """Wire the condensing-path mocks and return ``(em, stack, updateMeta)``.

        Args:
            handler: The live handler fixture.
            rows: Chronological context rows (oldest-first), as a test author
                naturally builds them (ascending ``messageId``/timestamp). The
                real ``getChatMessagesSince`` returns ``ORDER BY c.date DESC``
                (newest-first); the walk's ``deque.extendleft`` then reverses
                that back to oldest-first so ``sourceRows`` is chronological.
                To mirror production, this helper reverses ``rows`` before
                handing them to the mock.
            condensedRet: The condensed messages returned by ``condenseContext``.
            coverage: The coverage dict (``Dict[int, CondensingDict]``) returned
                by ``condenseContext``. Pre-populated with ready-made
                CondensingDicts (the new design computes coverage inside
                ``condenseContext``; the mock supplies it directly).

        Returns:
            A ``(em, stack, updateMetaMock)`` triple: the EnsuredMessage, an
            entered ExitStack (caller must ``with stack:``), and the
            ``updateChatMessageMetadata`` mock for post-call assertions.
        """
        handler.getChatSettings = AsyncMock(return_value=_condensingChatSettings())  # type: ignore[method-assign]
        # Reverse to newest-first to mirror production's ORDER BY c.date DESC;
        # the handler's deque.extendleft then yields oldest-first sourceRows.
        handler.db.chatMessages.getChatMessagesSince = AsyncMock(return_value=list(reversed(rows)))
        handler.llmService.condenseContext = AsyncMock(  # type: ignore[method-assign]
            return_value=(condensedRet, coverage)
        )
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=_modelRunResult("bot reply")
        )
        updateMetaMock = AsyncMock()
        handler.db.chatMessages.updateChatMessageMetadata = updateMetaMock  # type: ignore[method-assign]

        em = _liveEnsuredMessage()
        stack = contextlib.ExitStack()
        # Patch fromDBChatMessage so the walk doesn't touch the DB; return a
        # lightweight EM with empty metadata (no randomContext → no early break).
        stack.enter_context(
            patch.object(EnsuredMessage, "fromDBChatMessage", AsyncMock(return_value=_lightweightContextEM()))
        )
        # Each context message emits exactly ONE ModelMessage so the 1:1
        # alignment between contextMessages and contextRows is trivially exact.
        ctxMsg = ModelMessage(role="user", content="ctx-body")
        stack.enter_context(patch.object(EnsuredMessage, "toModelMessageList", AsyncMock(return_value=[ctxMsg])))
        # Avoid hitting the real LLM manager for model-typed settings.
        stack.enter_context(patch.object(ChatSettingsValue, "toModel", return_value=Mock()))
        return em, stack, updateMetaMock

    async def testCondensePersistsCondensingDictWithCoverage(self, liveHandler: LLMMessageHandler) -> None:
        """Single coverage batch → randomContext is a full CondensingDict.

        The mock returns ``{0: <CondensingDict with coverage fields>}``; the
        handler writes ``mergeCondensingDicts(coverage.values())`` to
        ``metadata["randomContext"]``.

        Args:
            liveHandler: Live handler fixture.
        """
        rows = [_makeContextRow(100 + i, f"user{i}", 1000.0 + i * 100.0) for i in range(10)]
        condensedRet = [ModelMessage(role="user", content="SUMMARY TEXT")]
        inputDict0 = CondensingDict(
            text="SUMMARY TEXT",
            messageIds=[MessageId(100 + i) for i in range(10)],
            participants=[f"user{i}" for i in range(10)],
            dateRange={"from": 1000.0, "to": 1900.0},
            messageCount=10,
        )
        coverage = {0: inputDict0}
        em, stack, updateMetaMock = self._wireCondensePath(
            liveHandler, rows=rows, condensedRet=condensedRet, coverage=coverage
        )

        with stack, patch("random.random", return_value=0.0):
            result = await liveHandler.handleRandomMessage(em, Mock())

        assert result is True
        updateMetaMock.assert_awaited_once()
        metadata = updateMetaMock.call_args.kwargs["metadata"]
        assert "randomContext" in metadata
        randomContext = metadata["randomContext"]

        # Shape: dict, not str (the P3b reshape).
        assert isinstance(randomContext, dict)
        # Delegation: randomContext is mergeCondensingDicts of the coverage values.
        assert randomContext == mergeCondensingDicts(coverage.values())
        # text matches the single-batch summary.
        assert randomContext["text"] == "SUMMARY TEXT"
        # Coverage fields populated (single batch → identity-ish merge).
        assert randomContext["messageIds"] == [MessageId(100 + i) for i in range(10)]
        assert set(randomContext["participants"]) == {f"user{i}" for i in range(10)}
        assert randomContext["messageCount"] == 10
        assert randomContext["dateRange"] == {"from": 1000.0, "to": 1900.0}

    async def testCondenseMultiBatchCoverageUnion(self, liveHandler: LLMMessageHandler) -> None:
        """Two coverage batches → randomContext is the merged union of both.

        The mock returns ``{0: <dict A>, 1: <dict B>}``; the handler writes
        ``mergeCondensingDicts(coverage.values())`` — messageIds concatenated,
        participants unioned, dateRange min/max, messageCount summed, text
        ``"\\n"``-joined.

        Args:
            liveHandler: Live handler fixture.
        """
        rows = [_makeContextRow(200 + i, f"sender{i}", 2000.0 + i * 100.0) for i in range(10)]
        condensedRet = [
            ModelMessage(role="user", content="BATCH1"),
            ModelMessage(role="user", content="BATCH2"),
        ]
        dictA = CondensingDict(
            text="BATCH1",
            messageIds=[MessageId(200 + i) for i in range(5)],
            participants=[f"sender{i}" for i in range(5)],
            dateRange={"from": 2000.0, "to": 2400.0},
            messageCount=5,
        )
        dictB = CondensingDict(
            text="BATCH2",
            messageIds=[MessageId(205 + i) for i in range(5)],
            participants=[f"sender{i}" for i in range(5, 10)],
            dateRange={"from": 2500.0, "to": 2900.0},
            messageCount=5,
        )
        coverage = {0: dictA, 1: dictB}
        em, stack, updateMetaMock = self._wireCondensePath(
            liveHandler, rows=rows, condensedRet=condensedRet, coverage=coverage
        )

        with stack, patch("random.random", return_value=0.0):
            result = await liveHandler.handleRandomMessage(em, Mock())

        assert result is True
        metadata = updateMetaMock.call_args.kwargs["metadata"]
        assert "randomContext" in metadata
        randomContext = metadata["randomContext"]

        # Delegation check.
        assert randomContext == mergeCondensingDicts(coverage.values())
        # Union properties: text "\n"-joined, messageIds concatenated (disjoint),
        # participants unioned, dateRange min/max, messageCount summed.
        assert randomContext["text"] == "BATCH1\nBATCH2"
        assert randomContext["messageIds"] == [MessageId(200 + i) for i in range(10)]
        assert set(randomContext["participants"]) == {f"sender{i}" for i in range(10)}
        assert randomContext["messageCount"] == 10
        assert randomContext["dateRange"] == {"from": 2000.0, "to": 2900.0}

    async def testCondenseEmptyCoverageSkipsWrite(self, liveHandler: LLMMessageHandler) -> None:
        """Empty coverage dict → randomContext is NOT written (F1 ``if condencedDictMap:`` guard).

        The mock returns ``(condensedRet, {})``; the handler's
        ``if condencedDictMap:`` guard is falsy, so ``metadata["randomContext"]``
        is never assigned. ``updateChatMessageMetadata`` is still called (it is
        outside the inner guard), but the persisted metadata lacks the key.

        Args:
            liveHandler: Live handler fixture.
        """
        rows = [_makeContextRow(300 + i, f"u{i}", 3000.0 + i * 100.0) for i in range(10)]
        condensedRet = [ModelMessage(role="user", content="FALLBACK SUMMARY")]
        coverage: dict[int, CondensingDict] = {}
        em, stack, updateMetaMock = self._wireCondensePath(
            liveHandler, rows=rows, condensedRet=condensedRet, coverage=coverage
        )

        with stack, patch("random.random", return_value=0.0):
            result = await liveHandler.handleRandomMessage(em, Mock())

        assert result is True
        updateMetaMock.assert_awaited_once()
        metadata = updateMetaMock.call_args.kwargs["metadata"]
        # Empty coverage → randomContext is NOT written (the write is skipped).
        assert "randomContext" not in metadata
