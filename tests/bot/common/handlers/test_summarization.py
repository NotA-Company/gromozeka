"""Tests for sessionId threading in :class:`SummarizationHandler._doSummarization`.

Covers the D3 prompt-cache-affinity decision: one summarization run maps to
one ``summary``-namespaced session bucket
(``gromozeka-summary-<chatId>-<messageId>``) computed once before the batch
loop, so every sequential batch of the run is sticky-routed to the same
prompt-cache bucket — deliberately disjoint from the live conversation
bucket.
"""

import datetime
from typing import List
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.summarization import SummarizationHandler
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
from internal.database.models import ChatMessageDict, MessageCategory
from internal.models import MessageId, MessageType
from internal.services.llm.service import LLMService
from lib.ai import ModelMessage, ModelResultStatus, ModelRunResult
from lib.ai.session import buildSessionId

# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mockConfigManager() -> Mock:
    """Create a mock ConfigManager for testing.

    Returns:
        Mock: Mocked ConfigManager instance with getBotConfig returning
        default bot configuration.
    """
    cm = Mock()
    cm.getBotConfig.return_value = {"token": "test_token", "owners": [123456]}
    cm.get.return_value = {}
    return cm


@pytest.fixture
def mockDatabase() -> Mock:
    """Create a mock Database for testing.

    Returns:
        Mock: Mocked Database instance with the chatMessages repository
        stubbed (``getChatMessagesSince`` overridden per test).
    """
    db = Mock()
    db.chatMessages = Mock()
    db.chatMessages.getChatMessagesSince = AsyncMock(return_value=[])
    return db


@pytest.fixture
def mockLlmService() -> Mock:
    """Create a mock LLMService with a mock LLMManager.

    Returns:
        Mock: Mocked LLMService instance with getLLMManager returning
        a mock manager; ``generateText`` is overridden per test.
    """
    service = Mock()
    manager = Mock()
    service.getLLMManager = Mock(return_value=manager)
    service.generateText = AsyncMock()
    return service


@pytest.fixture
def handler(
    mockConfigManager: Mock,
    mockDatabase: Mock,
    mockLlmService: Mock,
) -> SummarizationHandler:
    """Create a SummarizationHandler with all dependencies mocked.

    Args:
        mockConfigManager: Mocked configuration manager fixture
        mockDatabase: Mocked database fixture
        mockLlmService: Mocked LLM service fixture

    Returns:
        SummarizationHandler with injected mocks, ready for testing
    """
    # Patch singletons so BaseBotHandler.__init__ doesn't blow up
    with patch.object(LLMService, "getInstance", return_value=mockLlmService):
        with (
            patch("internal.bot.common.handlers.base.CacheService") as mockCacheCls,
            patch("internal.bot.common.handlers.base.QueueService") as mockQueueCls,
            patch("internal.bot.common.handlers.base.StorageService") as mockStorageCls,
        ):
            mockCacheCls.getInstance.return_value = Mock()
            mockQueueCls.getInstance.return_value = Mock()
            mockStorageCls.getInstance.return_value = Mock()
            h = SummarizationHandler(
                configManager=mockConfigManager,
                database=mockDatabase,
                botProvider=BotProvider.TELEGRAM,
            )  # type: ignore[call-arg]
    h.llmService = mockLlmService
    h.sendMessage = AsyncMock(return_value=[])  # type: ignore[assignment]
    return h


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chatSettings() -> ChatSettingsDict:
    """Build a complete chat-settings dict for the ``_doSummarization`` path.

    Production subscripts ``chatSettings[KEY]`` directly (no ``.get()``), so
    the dict must carry every key the summarization path reads:
    ``SUMMARY_PROMPT``, ``SUMMARY_MODEL`` and ``FALLBACK_HAPPENED_PREFIX``.
    ``SUMMARY_FALLBACK_MODEL`` is only forwarded to ``generateText`` as a
    key, never subscripted.

    Returns:
        A :class:`ChatSettingsDict` covering every key the summarization
        path reads.
    """
    return {
        ChatSettingsKey.SUMMARY_PROMPT: ChatSettingsValue("Summarize the chat"),
        ChatSettingsKey.SUMMARY_MODEL: ChatSettingsValue("dummy-summary-model"),
        ChatSettingsKey.FALLBACK_HAPPENED_PREFIX: ChatSettingsValue(""),
    }


def _makeEnsuredMessage(*, chatId: int = 777, messageId: int = 42) -> EnsuredMessage:
    """Build a real :class:`EnsuredMessage` to reply the summary to.

    Args:
        chatId: Recipient chat id (default 777).
        messageId: Message id (default 42); becomes the run's session tail.

    Returns:
        A fully constructed :class:`EnsuredMessage`.
    """
    return EnsuredMessage(
        sender=MessageSender(id=7, name="Alice", username="@alice"),
        recipient=MessageRecipient(id=chatId, chatType=ChatType.PRIVATE),
        messageId=messageId,
        date=datetime.datetime(2026, 9, 20, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText="/summary",
    )


def _makeDbChatMessage(messageId: int) -> ChatMessageDict:
    """Build a :class:`ChatMessageDict` row for ``fromDBChatMessage``.

    The row is deliberately minimal in content: no markup, metadata, media,
    reply or quote, so reconstructing it and ``formatForLLM(cache=None)``
    perform no database I/O.

    Args:
        messageId: Message id of the row.

    Returns:
        A :class:`ChatMessageDict` matching the shape
        ``EnsuredMessage.fromDBChatMessage`` reads.
    """
    return {
        "message_id": MessageId(messageId),
        "chat_id": 555,
        "user_id": 7,
        "full_name": "Alice",
        "username": "alice",
        "date": datetime.datetime(2026, 9, 20, 11, 0, 0, tzinfo=datetime.timezone.utc),
        "created_at": datetime.datetime(2026, 9, 20, 11, 0, 0, tzinfo=datetime.timezone.utc),
        "message_text": f"hello {messageId}",
        "message_type": MessageType.TEXT.value,
        "message_category": MessageCategory.USER,
        "reply_id": None,
        "quote_text": None,
        "thread_id": 0,
        "root_message_id": None,
        "media_id": None,
        "media_group_id": None,
        "markup": "",
        "metadata": "",
    }


def _modelRunResult(resultText: str) -> ModelRunResult:
    """Build a :class:`ModelRunResult` with ``FINAL`` status and given text.

    Args:
        resultText: The ``resultText`` the mocked LLM "returned".

    Returns:
        A ``ModelRunResult`` ready to be returned by the
        ``llmService.generateText`` stub.
    """
    return ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=resultText)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDoSummarizationSessionId:
    """Tests for the sticky per-run sessionId in ``_doSummarization``."""

    async def test_passesStickySessionIdToEveryBatch(
        self,
        handler: SummarizationHandler,
        mockLlmService: Mock,
        mockDatabase: Mock,
    ) -> None:
        """Every ``generateText`` batch call carries the same summary sessionId.

        The id is computed once before the batch loop as
        ``buildSessionId("summary", str(chatId), ensuredMessage.messageId.asStr())``
        and passed to each batch — one summarization run = one prompt-cache
        bucket, disjoint from the live conversation bucket. The setup drives
        the production batching math into TWO batches: ten messages with a
        deterministic 100-tokens-per-request-message estimate against a
        1000-token context → initial estimate 1100 → ``batchesCount = 2`` and
        ``batchLength = 5`` (per-batch re-checks estimate 600 ≤ 1000, so the
        slices are not shrunk further).

        Args:
            handler: The handler fixture with mocked dependencies
            mockLlmService: Mocked LLM service fixture
            mockDatabase: Mocked database fixture
        """
        # Ten DB messages → ten parsed messages → two 5-message batches.
        mockDatabase.chatMessages.getChatMessagesSince = AsyncMock(
            return_value=[_makeDbChatMessage(messageId) for messageId in range(1001, 1011)]
        )

        # Deterministic token estimate: 100 tokens per request message
        # (system + one per chat message) against a 1000-token context.
        mockModel = Mock()
        mockModel.contextSize = 1000
        mockModel.getEstimateTokensCount = Mock(side_effect=lambda reqMessages: len(reqMessages) * 100)
        mockManager = Mock()
        mockManager.getModel = Mock(return_value=mockModel)
        mockLlmService.getLLMManager = Mock(return_value=mockManager)

        generate = AsyncMock(return_value=_modelRunResult("batch summary"))
        handler.llmService.generateText = generate  # type: ignore[method-assign]

        em = _makeEnsuredMessage(chatId=777, messageId=42)

        # toModel() resolves the model via the module-level getLLMManager()
        # in internal.bot.models.chat_settings — patch it for determinism
        # (the real one caches a global and may trigger LLMService init).
        with patch("internal.bot.models.chat_settings.getLLMManager", return_value=mockManager):
            await handler._doSummarization(
                em,
                chatId=555,
                threadId=None,
                chatSettings=_chatSettings(),
                maxMessages=10,
                useCache=False,
                typingManager=Mock(),
            )

        # TWO separate batches were processed: each request carries the
        # system message plus a disjoint 5-message slice of the run.
        assert generate.await_count == 2
        firstBatch: List[ModelMessage] = list(generate.await_args_list[0].args[0])
        secondBatch: List[ModelMessage] = list(generate.await_args_list[1].args[0])
        assert len(firstBatch) == 6
        assert len(secondBatch) == 6
        firstContents = {message.content for message in firstBatch[1:]}
        secondContents = {message.content for message in secondBatch[1:]}
        assert firstContents.isdisjoint(secondContents)

        # ...and every batch received the ONE session id computed before
        # the loop (not a per-batch id).
        expectedSessionId = buildSessionId("summary", "555", em.messageId.asStr())
        assert expectedSessionId == "gromozeka-summary-555-42"
        for call in generate.await_args_list:
            assert call.kwargs["sessionId"] == expectedSessionId
