"""Tests for :class:`MessagePreprocessorHandler` embedding + memory-injection path.

The preprocessor sits in the message pipeline immediately after media processing
and ``saveChatMessage``. Once a message is durably persisted,
``newMessageHandler`` optionally generates a single embedding vector *inline*
(via ``self.llmService.generateEmbedding``) and reuses it for both chat-search
storage (``saveMessageEmbedding``) and memory injection. The inline path runs
when either:

* chat search is enabled (``[search-history].enabled`` server-wide **and** the
  per-chat ``EMBEDDINGS_ENABLED`` opt-in), or
* memory injection is enabled with embeddings (``MEMORY_ENABLED`` +
  ``EMBEDDINGS_ENABLED``). This combination selects the *semantic* memory
  retrieval path (cosine-similarity ranking); when ``MEMORY_ENABLED`` is on but
  ``EMBEDDINGS_ENABLED`` is off, memory injection still runs but falls back to
  *latest* retrieval (``injectMemories`` called with ``queryEmbedding=None``).

When memory injection is enabled but the embedding path did not run (or
returned ``None``), ``injectMemories`` is called with ``(None, None)`` as a
latest-retrieval fallback. The dedicated ``embedAndSaveMessage`` helper tests
live in ``tests/bot/common/handlers/test_chat_search.py`` (the helper was
re-homed onto :class:`ChatSearchHandler`).

This module covers every gate independently, plus the graceful-degradation
guarantee of the inline embedding path.
"""

import contextlib
import datetime
from typing import Any, AsyncIterator, Optional, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.base import HandlerResultStatus
from internal.bot.common.handlers.message_preprocessor import MessagePreprocessorHandler
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
    SingleMemoryDict,
)
from internal.bot.models.ensured_message import MediaContent
from internal.database.models import MemoryType, UserMemoryDict
from internal.database.utils import DEFAULT_THREAD_ID
from internal.models import MessageId
from internal.services.cache.service import CacheService
from internal.services.llm.service import LLMService
from internal.services.queue_service.service import QueueService
from internal.services.storage.service import StorageService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mockConfig() -> Mock:
    """Build a ConfigManager stub with sane defaults for the embedding path.

    Returns:
        Mock: A ``ConfigManager`` whose ``getSearchHistoryConfig()`` returns
        a config dict with ``enabled=True``. Tests override
        ``getSearchHistoryConfig`` directly when they need a different shape.
    """
    from internal.config.manager import ConfigManager

    cm = Mock(spec=ConfigManager)
    cm.getBotConfig.return_value = {"token": "test_token", "owners": [123456]}
    cm.getSearchHistoryConfig.return_value = {
        "enabled": True,
    }
    return cm


@pytest.fixture
def mockDb() -> Mock:
    """Build a Database stub with the repositories the handler exercises.

    Returns:
        Mock: A ``Database`` whose ``chatMessages`` and ``chatEmbeddings``
        are mocks with their save methods pre-configured as ``AsyncMock``s.
    """
    from internal.database import Database

    db = Mock(spec=Database)
    db.chatMessages = Mock()
    db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
    db.chatEmbeddings = Mock()
    db.chatEmbeddings.saveMessageEmbedding = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mockQueue() -> Mock:
    """Build a QueueService stub.

    Returns:
        Mock: A ``QueueService`` whose ``addBackgroundTask`` is an
        ``AsyncMock`` so the handler can ``await`` it.
    """
    service = Mock(spec=QueueService)
    service.addBackgroundTask = AsyncMock(return_value=None)
    return service


@pytest.fixture
def handler(
    mockConfig: Mock,
    mockDb: Mock,
    mockQueue: Mock,
) -> MessagePreprocessorHandler:
    """Construct a :class:`MessagePreprocessorHandler` with all deps mocked.

    The handler is wired with a real ``LLMService`` singleton (the autouse
    ``resetLlmServiceSingleton`` fixture resets it before each test). The
    ``generateEmbedding`` method on the singleton is replaced with an
    ``AsyncMock`` so the inline embedding path can be driven without touching
    the real model-resolution / rate-limit / provider chain. Individual tests
    override the mock's ``return_value`` to control success vs. failure.

    Args:
        mockConfig: ConfigManager stub.
        mockDb: Database stub.
        mockQueue: QueueService stub.

    Returns:
        A fully wired preprocessor with the async helper methods
        (``saveChatMessage``, ``processTelegramMedia``, ``getChatSettings``)
        stubbed at the instance level so each test can configure them.
    """
    with (
        patch.object(CacheService, "getInstance", return_value=Mock()),
        patch.object(QueueService, "getInstance", return_value=mockQueue),
        patch.object(StorageService, "getInstance", return_value=Mock()),
    ):
        h = MessagePreprocessorHandler(  # type: ignore[call-arg]
            configManager=mockConfig,
            database=mockDb,
            botProvider=BotProvider.TELEGRAM,
        )

    # Replace the handler-side helpers we don't want to exercise end-to-end.
    # saveChatMessage normally touches updateChatInfo + chatUsers + chatMessages;
    # we replace it with an AsyncMock returning True so the embedding block runs.
    h.saveChatMessage = AsyncMock(return_value=True)  # type: ignore[method-assign]

    # Telegram media processing is a no-op for these tests.
    h.processTelegramMedia = AsyncMock(return_value=None)  # type: ignore[method-assign]

    # Default chat-settings stub: EMBEDDINGS_ENABLED=true, EMBEDDING_MODEL="".
    h.getChatSettings = AsyncMock(return_value=_defaultChatSettings())  # type: ignore[method-assign]

    # generateEmbedding is the inline embedding boundary exercised by
    # newMessageHandler. Default to None (no vector produced) so tests that
    # do not care about embeddings get a clean no-op; tests that need a
    # successful embedding override the return_value.
    cast(Any, h).llmService.generateEmbedding = AsyncMock(return_value=None)  # type: ignore[method-assign]
    return h


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _defaultChatSettings(
    *,
    embeddingsEnabled: bool = True,
    embeddingModel: str = "",
) -> ChatSettingsDict:
    """Build a chat-settings dict with every key the preprocessor reads.

    Covers every code path exercised by the tests below:

    * the inline embedding block (``EMBEDDINGS_ENABLED`` / ``EMBEDDING_MODEL``),
      read by ``newMessageHandler`` to decide whether to embed for chat-search
      storage and memory-retrieval purposes, and
    * :meth:`MessagePreprocessorHandler.injectMemories`, whose master gate
      (``MEMORY_ENABLED``) is read by ``newMessageHandler``.
      ``newMessageHandler`` subscripts ``chatSettings`` directly for all of
      these keys before any guard, so a sparse dict missing any of them raises
      ``KeyError``.

    ``MEMORY_ENABLED`` defaults to ``"false"`` so ``injectMemories``
    is skipped unless a test explicitly opts in.

    Args:
        embeddingsEnabled: Value for ``EMBEDDINGS_ENABLED``.
        embeddingModel: Value for ``EMBEDDING_MODEL`` (empty string means
            "use the server-wide fallback").

    Returns:
        Mapping of every relevant :class:`ChatSettingsKey` to a
        :class:`ChatSettingsValue`.
    """
    return {
        ChatSettingsKey.EMBEDDINGS_ENABLED: ChatSettingsValue("true" if embeddingsEnabled else "false"),
        ChatSettingsKey.EMBEDDING_MODEL: ChatSettingsValue(embeddingModel),
        ChatSettingsKey.MEMORY_ENABLED: ChatSettingsValue("false"),
    }


def _makeEnsuredMessage(
    *,
    chatId: int = 100,
    messageId: int = 42,
    messageText: str = "hello world",
) -> Mock:
    """Build a mock :class:`EnsuredMessage` carrying the fields the handler reads.

    Args:
        chatId: Recipient chat id (default 100, >0 so private).
        messageId: Message id (default 42).
        messageText: Message text used for embedding (default ``"hello world"``).

    Returns:
        Mock: Spec-restricted mock with the attribute surface used by
        ``newMessageHandler`` (``recipient``, ``messageId``, ``messageText``,
        ``sender``, ``getBaseMessage``).
    """
    msg = Mock(spec=EnsuredMessage)
    msg.sender = MessageSender(id=7, name="Alice", username="alice")
    msg.recipient = MessageRecipient(id=chatId, chatType=ChatType.PRIVATE)
    msg.messageId = MessageId(messageId)
    msg.date = datetime.datetime(2026, 6, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
    msg.messageText = messageText
    msg.messageType = Mock()
    msg.replyId = None
    msg.quoteText = None
    msg.formatEntities = []
    msg.metadata = {}
    msg.mediaId = None
    msg.mediaContent = None
    msg.isReply = False
    # newMessageHandler calls getBaseMessage() after processTelegramMedia() to
    # detect Telegram "is_automatic_forward" (channel forwards). A non-Message
    # return value is the simplest way to skip that branch in unit tests.
    msg.getBaseMessage = Mock(return_value=Mock())
    return msg


def _realEnsuredMessageForEmbedding(
    *,
    messageText: str = "",
    mediaContent: Optional[str] = None,
) -> EnsuredMessage:
    """Build a real :class:`EnsuredMessage` for the formatted-text guard tests.

    A real instance (not a spec-mock) is needed because the embedding guard in
    :meth:`newMessageHandler` operates on the return value of
    ``formatForLLM(TEXT, useSingleMedia=False)``, and that method's TEXT branch
    prepends a ``<media-description>...</media-description>`` block when
    ``self.mediaContent`` is truthy. Using a real EnsuredMessage exercises that
    code path faithfully; a ``Mock(spec=EnsuredMessage)`` returns a truthy Mock
    from ``formatForLLM``, which defeats the guard entirely.

    When ``mediaContent`` is provided, the returned message is a media-only
    message: ``messageText`` is the raw text (typically empty), and the media
    attributes are pre-populated so ``formatForLLM`` emits the
    ``<media-description>`` block.

    :meth:`EnsuredMessage.updateMediaContent` is NOT stubbed here — callers
    must wrap the ``newMessageHandler`` call in::

        patch.object(EnsuredMessage, "updateMediaContent", AsyncMock(return_value=None))

    to prevent ``formatForLLM`` from polling the (mock) DB for media
    descriptions. ``EnsuredMessage`` uses ``__slots__``, so the patch must
    target the class, not the instance.

    Args:
        messageText: Raw message text (default ``""`` — an empty media-only
            message).
        mediaContent: Optional media description; when set, the returned
            message carries a ``mediaList`` entry and ``mediaContent``
            attribute so ``formatForLLM``'s TEXT branch prepends a
            ``<media-description>`` block.

    Returns:
        A real :class:`EnsuredMessage` with the given text and optional media.
    """
    msg = EnsuredMessage(
        sender=MessageSender(id=7, name="Alice", username="alice"),
        recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
        messageId=42,
        date=datetime.datetime(2026, 6, 20, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText=messageText,
    )
    msg.threadId = DEFAULT_THREAD_ID
    # setBaseMessage so getBaseMessage() doesn't raise; a plain Mock is not a
    # telegram.Message so the is_automatic_forward branch is skipped.
    msg.setBaseMessage(Mock())
    if mediaContent is not None:
        msg.mediaContent = mediaContent
        msg.mediaId = "media-1"
        msg.mediaList.append(MediaContent(id="media-1", content=mediaContent, processingInfo=None))
    return msg


# ---------------------------------------------------------------------------
# Tests: dispatch gating
# ---------------------------------------------------------------------------


class TestNewMessageHandlerDispatchGates:
    """Tests for the gates that control inline embedding generation.

    The refactor moved embedding generation inline into ``newMessageHandler``
    (no more ``queueService.addBackgroundTask`` dispatch). The boundary is now
    ``self.llmService.generateEmbedding`` (called once per message) followed by
    ``db.chatEmbeddings.saveMessageEmbedding`` when a vector is produced.
    """

    async def testNoDispatchServerDisabled(self, handler: MessagePreprocessorHandler, mockConfig: Mock) -> None:
        """Server-wide ``[search-history].enabled = false`` → no embedding generated.

        Args:
            handler: Preprocessor fixture.
            mockConfig: ConfigManager fixture, overridden to report disabled.
        """
        # ``_searchEnabled`` is cached at handler construction time, so we
        # must flip it on the instance directly (mutating the mock's
        # ``return_value`` post-construction would have no effect).
        handler._searchEnabled = False  # type: ignore[attr-defined]
        mockConfig.getSearchHistoryConfig.return_value = {"enabled": False}
        ensured = _makeEnsuredMessage(messageText="some text")

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        cast(Any, handler.llmService).generateEmbedding.assert_not_called()

    async def testNoDispatchPerChatDisabled(self, handler: MessagePreprocessorHandler) -> None:
        """Per-chat ``EMBEDDINGS_ENABLED = false`` → no embedding generated.

        Args:
            handler: Preprocessor fixture.
        """
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_defaultChatSettings(embeddingsEnabled=False)
        )
        ensured = _makeEnsuredMessage(messageText="some text")

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        cast(Any, handler.llmService).generateEmbedding.assert_not_called()

    async def testNoDispatchEmptyText(self, handler: MessagePreprocessorHandler) -> None:
        """Empty/whitespace FORMATTED text with no media does NOT trigger embedding.

        The embedding guard in ``newMessageHandler`` operates on the FORMATTED
        text (``formatForLLM(TEXT, useSingleMedia=False)`` output), not the raw
        ``messageText``. For a no-media message, ``formatForLLM(TEXT)`` returns
        the raw text verbatim, so whitespace-only text → formatted text is empty
        after ``.strip()`` → the embedding block is skipped.

        Every *other* gate is opened here (memory enabled, embeddings
        enabled, search enabled) so the empty-formatted-text guard is the
        only thing blocking ``generateEmbedding`` — proving it is the text
        guard, not some other gate, that prevents the embedding. Memory
        injection still runs via the latest-retrieval fallback
        (``injectMemories`` called with ``queryEmbedding=None``), so an
        empty-text message is not left without context.

        NOTE: This test alone does NOT distinguish a formatted guard from a raw
        guard — for no-media messages, formatted text equals raw text. See
        :meth:`testMediaOnlyMessageTriggersEmbedding` for the pin that
        distinguishes them.

        Args:
            handler: Preprocessor fixture.
        """
        # Every gate open except message text. Without the empty-text guard
        # this combination WOULD call generateEmbedding.
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value={
                ChatSettingsKey.EMBEDDINGS_ENABLED: ChatSettingsValue("true"),
                ChatSettingsKey.EMBEDDING_MODEL: ChatSettingsValue("text-embedding-3-small"),
                ChatSettingsKey.MEMORY_ENABLED: ChatSettingsValue("true"),
            }
        )
        # Spy on injectMemories so we can assert the latest-retrieval fallback
        # still fires for empty-text messages.
        handler.injectMemories = AsyncMock(return_value=None)  # type: ignore[method-assign]
        # The post-injection metadata update awaits this; wire it awaitable.
        handler.db.chatMessages.updateChatMessageMetadata = AsyncMock(return_value=None)  # type: ignore[attr-defined]
        # Real EnsuredMessage so formatForLLM returns the actual whitespace
        # text (a Mock(spec=EnsuredMessage) returns a truthy Mock from
        # formatForLLM, which defeats the guard).
        ensured = _realEnsuredMessageForEmbedding(messageText="   \n\t  ")

        with patch.object(EnsuredMessage, "updateMediaContent", AsyncMock(return_value=None)):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        cast(Any, handler.llmService).generateEmbedding.assert_not_called()
        handler.db.chatEmbeddings.saveMessageEmbedding.assert_not_called()  # type: ignore[attr-defined]
        # Memory injection still happened via the latest-retrieval fallback.
        handler.injectMemories.assert_awaited_once()  # type: ignore[attr-defined]
        callKwargs = handler.injectMemories.await_args.kwargs  # type: ignore[attr-defined]
        assert callKwargs["queryEmbedding"] is None

    async def testMediaOnlyMessageTriggersEmbedding(self, handler: MessagePreprocessorHandler) -> None:
        """Media-only message (empty raw text) DOES trigger embedding via the formatted guard.

        This is the key regression pin for the FORMATTED-text guard. A message
        with EMPTY raw ``messageText`` but a non-empty media description
        produces a non-empty ``formatForLLM(TEXT)`` output — the
        ``<media-description>...</media-description>`` block — so the embedding
        guard allows the embedding.

        If the guard were on RAW ``messageText`` instead of the formatted text,
        this message would be skipped (raw text is empty → ``.strip()`` is
        falsy → no embedding). The test FAILS under a raw-text guard and PASSES
        under the formatted guard — a true regression pin.

        The media content is set up via ``_realEnsuredMessageForEmbedding``
        which pre-populates ``mediaContent`` and ``mediaList`` so
        ``formatForLLM(TEXT, useSingleMedia=False)`` returns::

            <media-description>['A photo of a cat']</media-description>\\n\\n

        which is non-empty after ``.strip()``.

        Args:
            handler: Preprocessor fixture.
        """
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_defaultChatSettings(embeddingModel="text-embedding-3-small")
        )
        cast(Any, handler.llmService).generateEmbedding = AsyncMock(  # type: ignore[method-assign]
            return_value=("text-embedding-3-small", [0.1, 0.2, 0.3])
        )
        # Empty raw text but media content → formatForLLM produces a
        # <media-description> block, making the formatted text non-empty.
        ensured = _realEnsuredMessageForEmbedding(messageText="", mediaContent="A photo of a cat")

        with patch.object(EnsuredMessage, "updateMediaContent", AsyncMock(return_value=None)):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        cast(Any, handler.llmService).generateEmbedding.assert_awaited_once()
        handler.db.chatEmbeddings.saveMessageEmbedding.assert_awaited_once()  # type: ignore[attr-defined]

    async def testDispatchAllGatesPass(self, handler: MessagePreprocessorHandler) -> None:
        """All gates pass + embedding succeeds → ``saveMessageEmbedding`` invoked.

        Args:
            handler: Preprocessor fixture.
        """
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_defaultChatSettings(embeddingModel="text-embedding-3-small")
        )
        cast(Any, handler.llmService).generateEmbedding = AsyncMock(  # type: ignore[method-assign]
            return_value=("text-embedding-3-small", [0.1, 0.2, 0.3])
        )
        ensured = _realEnsuredMessageForEmbedding(messageText="meaningful text")

        with patch.object(EnsuredMessage, "updateMediaContent", AsyncMock(return_value=None)):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        cast(Any, handler.llmService).generateEmbedding.assert_awaited_once()
        handler.db.chatEmbeddings.saveMessageEmbedding.assert_awaited_once()  # type: ignore[attr-defined]
        saveKwargs = handler.db.chatEmbeddings.saveMessageEmbedding.await_args.kwargs  # type: ignore[attr-defined]
        assert saveKwargs["chatId"] == 100
        assert saveKwargs["embedding"] == [0.1, 0.2, 0.3]
        assert saveKwargs["model"] == "text-embedding-3-small"

    async def testEmbeddingFailureReturnsNext(self, handler: MessagePreprocessorHandler) -> None:
        """``generateEmbedding`` returns ``None`` → ``NEXT`` returned, no DB write.

        ``generateEmbedding`` swallows every internal failure (bad model,
        rate-limit, provider error) and surfaces it as ``None``. The inline
        path treats ``None`` as "no vector" and moves on: no
        ``saveMessageEmbedding`` call, no exception, the handler still returns
        ``NEXT``. This is the graceful-degradation guarantee that replaced the
        old dispatch-block never-crash wrapper.

        Args:
            handler: Preprocessor fixture.
        """
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_defaultChatSettings(embeddingModel="text-embedding-3-small")
        )
        cast(Any, handler.llmService).generateEmbedding = AsyncMock(return_value=None)  # type: ignore[method-assign]
        ensured = _realEnsuredMessageForEmbedding(messageText="meaningful text")

        with patch.object(EnsuredMessage, "updateMediaContent", AsyncMock(return_value=None)):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        cast(Any, handler.llmService).generateEmbedding.assert_awaited_once()
        handler.db.chatEmbeddings.saveMessageEmbedding.assert_not_called()  # type: ignore[attr-defined]

    async def test_semanticMemoryInjectionWhenEmbeddingsEnabled(self, handler: MessagePreprocessorHandler) -> None:
        """Both MEMORY_ENABLED + EMBEDDINGS_ENABLED → semantic ``injectMemories`` (non-None queryEmbedding).

        Pins the semantic-retrieval branch of ``newMessageHandler`` (~line 218):
        when both master gates are on and an embedding was produced,
        ``injectMemories`` is called with the embedding model and a NON-None
        ``queryEmbedding`` vector, and the latest-retrieval fallback (the
        ``if memoriesInjectionEnabled and not memoryInjected:`` block at
        ~line 223) is NOT reached — ``memoryInjected`` is set ``True`` by the
        semantic branch, so ``injectMemories`` fires exactly once.

        Args:
            handler: Preprocessor fixture.
        """
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value={
                ChatSettingsKey.EMBEDDINGS_ENABLED: ChatSettingsValue("true"),
                ChatSettingsKey.EMBEDDING_MODEL: ChatSettingsValue("text-embedding-3-small"),
                ChatSettingsKey.MEMORY_ENABLED: ChatSettingsValue("true"),
            }
        )
        cast(Any, handler.llmService).generateEmbedding = AsyncMock(  # type: ignore[method-assign]
            return_value=("test-model", [0.1, 0.2, 0.3])
        )
        # Spy on injectMemories so we can assert the semantic branch's call args;
        # the post-injection metadata update must also be awaitable.
        handler.injectMemories = AsyncMock(return_value=None)  # type: ignore[method-assign]
        handler.db.chatMessages.updateChatMessageMetadata = AsyncMock(return_value=None)  # type: ignore[attr-defined]
        ensured = _realEnsuredMessageForEmbedding(messageText="meaningful text")

        with patch.object(EnsuredMessage, "updateMediaContent", AsyncMock(return_value=None)):
            result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        cast(Any, handler.llmService).generateEmbedding.assert_awaited_once()
        # Semantic branch: injectMemories called with a NON-None queryEmbedding.
        handler.injectMemories.assert_awaited_once()  # type: ignore[attr-defined]
        callKwargs = handler.injectMemories.await_args.kwargs  # type: ignore[attr-defined]
        assert callKwargs["queryEmbedding"] is not None
        assert callKwargs["queryEmbedding"] == [0.1, 0.2, 0.3]
        # The latest-retrieval fallback must NOT have fired: the semantic branch
        # set memoryInjected=True, so injectMemories was called exactly once.
        assert handler.injectMemories.await_count == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Tests: _searchEnabled construction-time caching (Fix 8)
# ---------------------------------------------------------------------------


class TestSearchEnabledCaching:
    """Regression tests for ``_searchEnabled`` being captured at construction.

    Fix 8 (June 2026) moved the ``[search-history].enabled`` read out of
    the per-message dispatch hot path and into ``__init__``, so every
    message avoids a ``ConfigManager`` round-trip. The trade-off: a
    config flip now requires a bot restart to take effect. These tests
    pin the new contract down so a future refactor cannot quietly
    regress to the per-call read.
    """

    async def test_constructorCachesEnabledTrue(self, mockConfig: Mock) -> None:
        """``[search-history].enabled = true`` at construction → ``_searchEnabled = True``.

        Args:
            mockConfig: ConfigManager stub fixture (already configured
                with ``enabled=True`` in the default fixture body).
        """
        with (
            patch.object(LLMService, "getInstance", return_value=Mock()),
            patch.object(CacheService, "getInstance", return_value=Mock()),
            patch.object(QueueService, "getInstance", return_value=Mock()),
            patch.object(StorageService, "getInstance", return_value=Mock()),
        ):
            h = MessagePreprocessorHandler(  # type: ignore[call-arg]
                configManager=mockConfig,
                database=Mock(),
                botProvider=BotProvider.TELEGRAM,
            )

        assert h._searchEnabled is True  # type: ignore[attr-defined]

    async def test_constructorCachesEnabledFalse(self, mockConfig: Mock) -> None:
        """``[search-history].enabled = false`` at construction → ``_searchEnabled = False``.

        Args:
            mockConfig: ConfigManager stub fixture — overridden to
                report ``enabled=False`` *before* construction so the
                cached value reflects the startup state.
        """
        mockConfig.getSearchHistoryConfig.return_value = {"enabled": False}

        with (
            patch.object(LLMService, "getInstance", return_value=Mock()),
            patch.object(CacheService, "getInstance", return_value=Mock()),
            patch.object(QueueService, "getInstance", return_value=Mock()),
            patch.object(StorageService, "getInstance", return_value=Mock()),
        ):
            h = MessagePreprocessorHandler(  # type: ignore[call-arg]
                configManager=mockConfig,
                database=Mock(),
                botProvider=BotProvider.TELEGRAM,
            )

        assert h._searchEnabled is False  # type: ignore[attr-defined]

    async def test_postConstructionConfigFlipHasNoEffect(self, mockConfig: Mock) -> None:
        """A config flip after construction does not change the cached value.

        Builds a handler with ``enabled=False``, then mutates the mock
        to report ``enabled=True``, then invokes the inline embedding path —
        no embedding should be generated. The cached value must win; the test
        guards against a future "fix" that re-reads the config on every
        message and re-introduces the round-trip.

        Args:
            mockConfig: ConfigManager stub fixture.
        """
        # Start disabled.
        mockConfig.getSearchHistoryConfig.return_value = {"enabled": False}

        with (
            patch.object(LLMService, "getInstance", return_value=Mock()),
            patch.object(CacheService, "getInstance", return_value=Mock()),
            patch.object(QueueService, "getInstance", return_value=AsyncMock()),
            patch.object(StorageService, "getInstance", return_value=Mock()),
        ):
            h = MessagePreprocessorHandler(  # type: ignore[call-arg]
                configManager=mockConfig,
                database=Mock(),
                botProvider=BotProvider.TELEGRAM,
            )
            h.saveChatMessage = AsyncMock(return_value=True)  # type: ignore[method-assign]
            h.processTelegramMedia = AsyncMock(return_value=None)  # type: ignore[method-assign]
            h.getChatSettings = AsyncMock(return_value=_defaultChatSettings())  # type: ignore[method-assign]

        # Flip the config to "enabled" after construction.
        mockConfig.getSearchHistoryConfig.return_value = {"enabled": True}

        ensured = _makeEnsuredMessage(messageText="meaningful text")
        result = await h.newMessageHandler(ensured, updateObj=Mock())

        # The handler still returns NEXT, but the embedding path is gated
        # by the cached flag and must NOT call generateEmbedding.
        assert result is HandlerResultStatus.NEXT
        cast(Any, h.llmService).generateEmbedding.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: chat-member handlers (join / leave) route through the cache
# ---------------------------------------------------------------------------


def _wireCacheForChatMember(handler: MessagePreprocessorHandler) -> Mock:
    """Install awaitable cache mocks for the chat-member handler paths.

    The ``handler`` fixture wires ``handler.cache`` to a bare ``Mock()`` (via
    ``patch.object(CacheService, "getInstance", ...)``), whose auto-created
    child mocks are not awaitable. The join/leave handlers await
    ``cache.updateChatUser`` / ``cache.getUserMetadata`` /
    ``cache.updateUserMetadata``, so those three must be ``AsyncMock``s for the
    handlers to run at all. ``setUserMetadata(isUpdate=True)`` also acquires
    ``cache.chatUserMetadataLock()`` (an async context manager), so that is wired
    to a no-op stand-in. Returns the wired cache so the caller can assert on the
    recorded calls.

    Args:
        handler: Preprocessor fixture.

    Returns:
        The handler's cache mock with the async methods installed.
    """

    @contextlib.asynccontextmanager
    async def _noopMetadataLock() -> AsyncIterator[None]:
        """No-op async CM stand-in for ``CacheService.chatUserMetadataLock``."""
        yield

    cache = cast(Any, handler.cache)
    cache.updateChatUser = AsyncMock(return_value=None)
    # Non-empty baseline with a sibling key the merge must preserve. If
    # ``setUserMetadata(isUpdate=True)`` regresses and drops the
    # ``{**existing, **metadata}`` shallow merge, ``memoryRefinement`` is
    # absent from the recorded metadata and the assertions in the join/leave
    # tests fail — which is the whole point.
    cache.getUserMetadata = AsyncMock(return_value={"memoryRefinement": {"0": {"summary": "pre-existing"}}})
    cache.updateUserMetadata = AsyncMock(return_value=None)
    cache.chatUserMetadataLock = _noopMetadataLock
    return cache


class TestChatMemberHandlers:
    """Tests for ``newChatMemberHandler`` / ``leftChatMemberHandler``.

    Both handlers were refactored (Phase 3 of the write-through ``chat_users``
    cache) to route their ``chat_users`` write through
    ``self.cache.updateChatUser`` instead of the raw ``db.chatUsers.updateChatUser``
    repo call. These tests pin the cache routing down so a future refactor
    cannot silently revert to the raw repo.
    """

    async def test_newChatMemberHandler_routesUpdateChatUserThroughCache(
        self, handler: MessagePreprocessorHandler
    ) -> None:
        """``newChatMemberHandler`` writes via ``cache.updateChatUser`` with the member's args.

        Drives the handler with ``messageId=None`` so the delete-message branch
        (which needs ``self._bot``) is skipped; the result is ``NEXT``. Asserts
        the cache's ``updateChatUser`` was awaited once with the exact
        ``(chatId, userId, username, fullName)`` of the joining member, and that
        the follow-up ``setUserMetadata(isUpdate=True)`` also routed its write
        through ``cache.updateUserMetadata``.

        Args:
            handler: Preprocessor fixture.
        """
        cache = _wireCacheForChatMember(handler)
        targetChat = MessageRecipient(id=100, chatType=ChatType.GROUP)
        newMember = MessageSender(id=7, name="Alice", username="alice")

        result = await handler.newChatMemberHandler(
            targetChat=targetChat,
            messageId=None,
            newMember=newMember,
            updateObj=Mock(),
        )

        assert result is HandlerResultStatus.NEXT
        cache.updateChatUser.assert_awaited_once_with(chatId=100, userId=7, username="alice", fullName="Alice")
        # setUserMetadata(isUpdate=True) reads ``getUserMetadata`` then writes the
        # shallow-merged ``{**existing, **{"leftChat": False}}`` via
        # ``updateUserMetadata``. The pre-existing ``memoryRefinement`` sibling
        # must survive the merge — this assertion proves the merge happened.
        cache.updateUserMetadata.assert_awaited_once_with(
            chatId=100,
            userId=7,
            metadata={"memoryRefinement": {"0": {"summary": "pre-existing"}}, "leftChat": False},
        )

    async def test_leftChatMemberHandler_routesUpdateChatUserThroughCache(
        self, handler: MessagePreprocessorHandler
    ) -> None:
        """``leftChatMemberHandler`` writes via ``cache.updateChatUser`` with the member's args.

        Same shape as the join test but for the leave path; the metadata flag
        written is ``{"leftChat": True}`` rather than ``{"leftChat": False}``.

        Args:
            handler: Preprocessor fixture.
        """
        cache = _wireCacheForChatMember(handler)
        targetChat = MessageRecipient(id=200, chatType=ChatType.GROUP)
        leftMember = MessageSender(id=9, name="Bob", username="bob")

        result = await handler.leftChatMemberHandler(
            targetChat=targetChat,
            messageId=None,
            leftMember=leftMember,
            updateObj=Mock(),
        )

        assert result is HandlerResultStatus.NEXT
        cache.updateChatUser.assert_awaited_once_with(chatId=200, userId=9, username="bob", fullName="Bob")
        # Same shallow-merge proof as the join test: ``memoryRefinement`` must
        # survive the ``{**existing, **{"leftChat": True}}`` merge.
        cache.updateUserMetadata.assert_awaited_once_with(
            chatId=200,
            userId=9,
            metadata={"memoryRefinement": {"0": {"summary": "pre-existing"}}, "leftChat": True},
        )


# ---------------------------------------------------------------------------
# Tests: injectMemories compact-format write path (memory-compaction-v1 Phase 3a)
# ---------------------------------------------------------------------------


def _chatSettingsWithMemoryInjection() -> ChatSettingsDict:
    """Build chat settings enabling memory injection (``MEMORY_ENABLED=true``).

    The default ``handler`` fixture wires ``getChatSettings`` to
    ``_defaultChatSettings()`` which sets ``MEMORY_ENABLED=false`` so
    ``injectMemories`` is skipped. These tests need the master memory gate
    enabled. ``EMBEDDINGS_ENABLED`` is left false because the latest vs.
    semantic distinction is a ``newMessageHandler`` concern (driven by the
    ``MEMORY_ENABLED && EMBEDDINGS_ENABLED`` gate there), not this helper's —
    the compact-format write path in :meth:`injectMemories` is agnostic to it.

    Returns:
        A chat-settings dict with ``MEMORY_ENABLED`` enabled.
    """
    return {
        ChatSettingsKey.MEMORY_ENABLED: ChatSettingsValue("true"),
        ChatSettingsKey.EMBEDDINGS_ENABLED: ChatSettingsValue("false"),
        ChatSettingsKey.EMBEDDING_MODEL: ChatSettingsValue(""),
    }


def _realEnsuredMessage(messageText: str = "hello world") -> EnsuredMessage:
    """Build a real :class:`EnsuredMessage` for the injectMemories write-path tests.

    A real instance (not a spec-mock) is needed because ``injectMemories``
    subscripts ``metadata`` (a real dict, which a spec-mock does not support);
    we then assert on the resulting compact-ID shape.

    Args:
        messageText: Message text (unused by the latest-retrieval branch but
            kept for completeness).

    Returns:
        A freshly constructed :class:`EnsuredMessage`.
    """
    msg = EnsuredMessage(
        sender=MessageSender(id=7, name="Alice", username="alice"),
        recipient=MessageRecipient(id=100, chatType=ChatType.PRIVATE),
        messageId=42,
        date=datetime.datetime(2026, 6, 20, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText=messageText,
    )
    msg.threadId = DEFAULT_THREAD_ID
    return msg


def _permanentSingleMemory(memoryId: str, content: str) -> SingleMemoryDict:
    """Build a permanent :class:`SingleMemoryDict` carrying an ``id``.

    Mirrors the ``keepId=True`` output of the permanent-memories cache loader
    (``CacheService.getChatUserPermanentMemories``) so the write path can extract
    ``permanentIds`` from the ``id`` field.

    Args:
        memoryId: Memory UUID hex.
        content: Memory body text.

    Returns:
        A :class:`SingleMemoryDict` with an ``id`` key.
    """
    return {"id": memoryId, "type": MemoryType.FACT, "content": content, "tags": ["bio"]}


def _dbUserMemory(memoryId: str, content: str) -> UserMemoryDict:
    """Build a minimal :class:`UserMemoryDict` carrying ``memory_id``.

    Mirrors the row shape returned by ``getLatestMemories``. Only the keys
    consumed by the write path (``memory_id``) and the
    ``convertDBMemoryToSingleMemoryDict`` converter (``type``/``tags``/``content``)
    are populated.

    Args:
        memoryId: Memory UUID hex.
        content: Memory body text.

    Returns:
        A minimal :class:`UserMemoryDict`.
    """
    return cast(
        UserMemoryDict,
        {"memory_id": memoryId, "type": MemoryType.PREFERENCE, "content": content, "tags": ["recent"]},
    )


class TestInjectMemoriesCompactFormat:
    """Tests for the compact memory-ID write path in :meth:`injectMemories`.

    Phase 3+: ``injectMemories`` stores compact ID lists
    (``permanentIds``/``shortTermIds``) in ``metadata["memories"]`` for
    persistence. The permanent-memories cache loader carries ``id``
    (``keepId=True``) so ``permanentIds`` is extractable; resolution to content
    happens lazily in :meth:`EnsuredMessage.formatForLLM` via
    ``cache.getMemoriesByIds`` at render time (no ``id`` leaks — the converter
    strips it via ``keepId=False``).
    """

    def _wireForInjection(
        self,
        handler: MessagePreprocessorHandler,
        *,
        permanentMemories: list[SingleMemoryDict],
        dbMemories: list[UserMemoryDict],
    ) -> EnsuredMessage:
        """Wire cache/db/getChatSettings for the latest-retrieval injectMemories path.

        Args:
            handler: Preprocessor fixture (cache/db already mocked).
            permanentMemories: Permanent memories the cache returns (carry ``id``).
            dbMemories: Short-term memories the DB returns (carry ``memory_id``).

        Returns:
            A real :class:`EnsuredMessage` ready to be passed to ``injectMemories``.
        """
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_chatSettingsWithMemoryInjection()
        )
        cache = cast(Any, handler.cache)
        cache.getChatUserPermanentMemories = AsyncMock(return_value=permanentMemories)
        handler.db.userMemories.getLatestMemories = AsyncMock(return_value=dbMemories)  # type: ignore[attr-defined]
        return _realEnsuredMessage()

    async def test_injectMemories_writesCompactIdsToMetadata(self, handler: MessagePreprocessorHandler) -> None:
        """``metadata["memories"]`` carries ``permanentIds``/``shortTermIds``, not content.

        Regression guard for the compact-format write contract: the persisted
        shape must be the ID lists (what gets saved into ``chat_messages.metadata``).

        Args:
            handler: Preprocessor fixture.
        """
        msg = self._wireForInjection(
            handler,
            permanentMemories=[_permanentSingleMemory("perm-1", "vegan")],
            dbMemories=[_dbUserMemory("short-1", "just woke up")],
        )

        await handler.injectMemories(msg, None, None)

        stored = msg.metadata.get("memories")
        assert stored is not None
        assert "permanentIds" in stored  # type: ignore[operator]
        assert "shortTermIds" in stored  # type: ignore[operator]
        assert "permanent" not in stored  # type: ignore[operator]
        assert "shortTerm" not in stored  # type: ignore[operator]
        assert stored["permanentIds"] == ["perm-1"]  # type: ignore[index]
        assert stored["shortTermIds"] == ["short-1"]  # type: ignore[index]

    async def test_injectMemories_permanentIdsNonEmptyConfirmsKeepId(self, handler: MessagePreprocessorHandler) -> None:
        """``permanentIds`` is non-empty when a permanent memory carries ``id``.

        Confirms the ``keepId=True`` loader fix flows through end-to-end: the
        permanent cache returns entries with ``id``, and the write path extracts
        them. Without ``keepId=True`` the permanent entries would lack ``id`` and
        ``permanentIds`` would be empty.

        Args:
            handler: Preprocessor fixture.
        """
        msg = self._wireForInjection(
            handler,
            permanentMemories=[
                _permanentSingleMemory("perm-1", "vegan"),
                _permanentSingleMemory("perm-2", "lives in Berlin"),
            ],
            dbMemories=[],
        )

        await handler.injectMemories(msg, None, None)

        stored = msg.metadata.get("memories")
        assert stored is not None
        assert stored["permanentIds"] == ["perm-1", "perm-2"]  # type: ignore[index]

    async def test_injectMemories_dropsFalsyMemoryIds(self, handler: MessagePreprocessorHandler) -> None:
        """A short-term memory whose ``memory_id`` is falsy is dropped from ``shortTermIds``.

        Defensive filter (``if m.get("memory_id")``) so a malformed row never
        writes ``None`` into the ID list.

        Args:
            handler: Preprocessor fixture.
        """
        malformed = cast(UserMemoryDict, {"memory_id": "", "type": MemoryType.PREFERENCE, "content": "x", "tags": []})
        msg = self._wireForInjection(
            handler,
            permanentMemories=[],
            dbMemories=[malformed, _dbUserMemory("short-1", "real")],
        )

        await handler.injectMemories(msg, None, None)

        stored = msg.metadata.get("memories")
        assert stored is not None
        assert stored["shortTermIds"] == ["short-1"]  # type: ignore[index]

    async def test_injectMemories_semanticMode_writesScores(self, handler: MessagePreprocessorHandler) -> None:
        """Semantic mode writes ``shortTermScores`` mapping memory IDs to search scores.

        When ``queryEmbedding`` is non-None (semantic mode), ``injectMemories`` extracts
        the ``score`` field from each short-term memory returned by ``searchMemories``
        and writes a ``shortTermScores`` map keyed by ``memory_id`` into
        ``metadata["memories"]``. The scores are preserved as floats.

        Args:
            handler: Preprocessor fixture.
        """
        # Wire the semantic search path instead of latest retrieval.
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_chatSettingsWithMemoryInjection()
        )
        cache = cast(Any, handler.cache)
        cache.getChatUserPermanentMemories = AsyncMock(return_value=[])
        # Semantic search returns UserMemoryDict entries with ``score`` keys.
        semanticResults = [
            cast(
                UserMemoryDict,
                {
                    "memory_id": "short-1",
                    "type": MemoryType.PREFERENCE,
                    "content": "likes coffee",
                    "tags": ["recent"],
                    "score": 0.95,
                },
            ),
            cast(
                UserMemoryDict,
                {
                    "memory_id": "short-2",
                    "type": MemoryType.EVENT,
                    "content": "just woke up",
                    "tags": [],
                    "score": 0.87,
                },
            ),
        ]
        handler.db.userMemories.searchMemories = AsyncMock(return_value=semanticResults)  # type: ignore[attr-defined]

        msg = _realEnsuredMessage()

        # Call injectMemories with a non-None queryEmbedding to trigger semantic mode.
        await handler.injectMemories(msg, "test-model", queryEmbedding=[0.1, 0.2])

        stored = msg.metadata.get("memories")
        assert stored is not None
        assert "shortTermScores" in stored  # type: ignore[operator]
        assert stored["shortTermScores"] == {  # type: ignore[index]
            "short-1": 0.95,
            "short-2": 0.87,
        }

    async def test_injectMemories_latestMode_noScores(self, handler: MessagePreprocessorHandler) -> None:
        """Latest mode (fallback path) omits ``shortTermScores`` from metadata.

        When ``queryEmbedding`` is ``None`` (latest-retrieval fallback), short-term
        memories are fetched via ``getLatestMemories`` which does not provide scores.
        The ``shortTermScores`` key must NOT appear in ``metadata["memories"]``.

        Args:
            handler: Preprocessor fixture.
        """
        msg = self._wireForInjection(
            handler,
            permanentMemories=[],
            dbMemories=[_dbUserMemory("short-1", "real")],
        )

        # Call injectMemories with queryEmbedding=None to trigger latest mode.
        await handler.injectMemories(msg, None, None)

        stored = msg.metadata.get("memories")
        assert stored is not None
        assert "shortTermScores" not in stored  # type: ignore[operator]