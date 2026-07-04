"""Tests for the bot-answer probability gate in :class:`LLMMessageHandler`.

When a message arrives from a sender whose username ends with ``"bot"`` (i.e.
likely another bot), ``newMessageHandler`` consults the per-chat
``BOT_ANSWER_PROBABILITY`` setting and probabilistically skips the message:

* ``0.0`` — never answer bots (always ``SKIPPED``),
* ``1.0`` — always answer bots (never skipped),
* anything in between — answer with that probability.

This module exercises the gate in isolation: the downstream handlers
(``handleReply`` / ``handleMention`` / ``handleRandomMessage``) are stubbed so
the gate is the only logic under test. ``BotProvider.MAX`` is used so the
Telegram-only ``is_automatic_forward`` branch is skipped (the gate itself is
provider-agnostic).
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.base import HandlerResultStatus
from internal.bot.common.handlers.llm_messages import LLMMessageHandler
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
)
from internal.models import MessageId
from internal.services.cache.service import CacheService
from internal.services.queue_service.service import QueueService
from internal.services.storage.service import StorageService

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
