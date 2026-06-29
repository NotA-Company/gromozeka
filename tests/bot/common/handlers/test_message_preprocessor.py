"""Tests for :class:`MessagePreprocessorHandler` embedding-dispatch hook.

The preprocessor sits in the message pipeline immediately after media processing
and ``saveChatMessage``. Once a message is durably persisted it can optionally
dispatch a background task that generates and stores an embedding vector
(``embedAndSaveMessage``) — but only if:

* ``[search-history].enabled`` is true (server-wide feature flag),
* the per-chat setting ``EMBEDDINGS_ENABLED`` is true (chat opt-in),
* the message has non-empty text.

This module covers every gate independently, plus the three failure modes of
``embedAndSaveMessage`` and the never-crash guarantee of the dispatch block.
"""

import datetime
from typing import Any, cast
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
)
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
        Mock: A ``Database`` whose ``chatMessages``, ``chatEmbeddings`` and
        ``chatUsers`` are mocks with ``saveMessageEmbedding`` pre-configured
        as an ``AsyncMock``.
    """
    from internal.database import Database

    db = Mock(spec=Database)
    db.chatMessages = Mock()
    db.chatMessages.saveChatMessage = AsyncMock(return_value=None)
    db.chatEmbeddings = Mock()
    db.chatEmbeddings.saveMessageEmbedding = AsyncMock(return_value=None)
    db.chatUsers = Mock()
    db.chatUsers.updateChatUser = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mockLlmManager() -> Mock:
    """Build a mock LLMManager for the handler's LLM service.

    The autouse ``resetLlmServiceSingleton`` fixture has already
    reset the ``LLMService`` singleton before this fixture runs, so
    patching ``getLLMManager`` on the singleton is safe and stays in
    effect for the whole test (the patch lives on the singleton
    instance, which is what ``embedAndSaveMessage`` looks up via
    ``LLMService.getInstance()``).

    Returns:
        Mock: An ``LLMManager`` whose ``getModel(name)`` returns
        ``None`` by default. Tests assign their own ``getModel``
        behaviour to control whether a model is found.
    """
    manager = Mock()
    manager.getModel = Mock(return_value=None)
    manager.listModels = Mock(return_value=[])
    return manager


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
    mockLlmManager: Mock,
    mockQueue: Mock,
) -> MessagePreprocessorHandler:
    """Construct a :class:`MessagePreprocessorHandler` with all deps mocked.

    The handler is wired with a real ``LLMService`` singleton (the
    autouse ``resetLlmServiceSingleton`` fixture has already reset
    it). The ``getLLMManager`` method on the singleton is patched to
    return ``mockLlmManager`` so each test can drive model resolution
    via ``mockLlmManager.getModel``. ``embedAndSaveMessage`` looks up
    the LLM service via ``LLMService.getInstance()`` (the same
    singleton) so the patch is in effect for both the dispatch path
    and the helper.

    Args:
        mockConfig: ConfigManager stub.
        mockDb: Database stub.
        mockLlmManager: Mock LLMManager.
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

    # llmService attribute was set by BaseBotHandler.__init__ from the
    # real singleton; install the mock LLMManager on it so the
    # embedding helper sees the same patched manager.
    cast(Any, h).llmService.getLLMManager = Mock(return_value=mockLlmManager)
    return h


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _defaultChatSettings(
    *,
    embeddingsEnabled: bool = True,
    embeddingModel: str = "",
) -> ChatSettingsDict:
    """Build a chat-settings dict with the keys the embedding block reads.

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


# ---------------------------------------------------------------------------
# Tests: dispatch gating
# ---------------------------------------------------------------------------


class TestNewMessageHandlerDispatchGates:
    """Tests for the three gates that block embedding dispatch."""

    async def testNoDispatchServerDisabled(self, handler: MessagePreprocessorHandler, mockConfig: Mock) -> None:
        """Server-wide ``[search-history].enabled = false`` → no task scheduled.

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
        handler.queueService.addBackgroundTask.assert_not_called()  # type: ignore[attr-defined]

    async def testNoDispatchPerChatDisabled(self, handler: MessagePreprocessorHandler) -> None:
        """Per-chat ``EMBEDDINGS_ENABLED = false`` → no task scheduled.

        Args:
            handler: Preprocessor fixture.
        """
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_defaultChatSettings(embeddingsEnabled=False)
        )
        ensured = _makeEnsuredMessage(messageText="some text")

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        handler.queueService.addBackgroundTask.assert_not_called()  # type: ignore[attr-defined]

    async def testNoDispatchEmptyText(self, handler: MessagePreprocessorHandler) -> None:
        """All gates pass, but ``messageText`` is whitespace-only → no task scheduled.

        Args:
            handler: Preprocessor fixture.
        """
        ensured = _makeEnsuredMessage(messageText="   \n\t  ")

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        handler.queueService.addBackgroundTask.assert_not_called()  # type: ignore[attr-defined]

    async def testDispatchAllGatesPass(self, handler: MessagePreprocessorHandler) -> None:
        """All gates pass (incl. non-empty model name) → ``addBackgroundTask`` called once.

        Args:
            handler: Preprocessor fixture.
        """
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_defaultChatSettings(embeddingModel="text-embedding-3-small")
        )
        ensured = _makeEnsuredMessage(messageText="meaningful text")

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        handler.queueService.addBackgroundTask.assert_awaited_once()  # type: ignore[attr-defined]
        # The argument should be a coroutine (asyncio.create_task wraps a coroutine).
        taskArg = handler.queueService.addBackgroundTask.await_args.args[0]  # type: ignore[attr-defined]
        # asyncio.Task is created from a coroutine; we just sanity-check it is awaitable-ish.
        assert taskArg is not None


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
        to report ``enabled=True``, then invokes the dispatch path —
        no background task should be scheduled. The cached value must
        win; the test guards against a future "fix" that re-reads the
        config on every message and re-introduces the round-trip.

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

        # The handler still returns NEXT, but the dispatch path is gated
        # by the cached flag and must NOT call addBackgroundTask.
        assert result is HandlerResultStatus.NEXT
        h.queueService.addBackgroundTask.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Tests: embedAndSaveMessage failure handling
# ---------------------------------------------------------------------------


class TestEmbedMessage:
    """Tests for the shared ``embedAndSaveMessage`` helper as invoked by the preprocessor.

    The preprocessor hands off the real ``EnsuredMessage`` it just
    saved to the helper (which resolves the LLM singleton internally
    and writes the vector via ``db.chatEmbeddings.saveMessageEmbedding``).
    The three failure modes below cover the helper's never-crash
    contract: model missing, embedding API raising, and the happy
    path. The dispatch-block never-crash guarantee is its own test.
    """

    async def _runHelper(self, handler: MessagePreprocessorHandler, modelName: str) -> None:
        """Call ``embedAndSaveMessage`` with an ``EnsuredMessage``.

        Args:
            handler: Preprocessor fixture.
            modelName: Embedding model name.
        """
        from internal.bot.common.embedding_utils import embedAndSaveMessage

        ensured = _makeEnsuredMessage(messageText="hello")
        await embedAndSaveMessage(
            ensuredMessage=ensured,
            modelName=modelName,
            db=handler.db,
        )

    async def testEmbedMessageModelNotFound(self, handler: MessagePreprocessorHandler) -> None:
        """``getModel`` returns None → logged warning, no crash, no DB write.

        Args:
            handler: Preprocessor fixture.
        """
        handler.llmService.getLLMManager().getModel = Mock(return_value=None)  # type: ignore[attr-defined]

        # Should not raise.
        await self._runHelper(handler, modelName="missing-model")

        handler.db.chatEmbeddings.saveMessageEmbedding.assert_not_called()  # type: ignore[attr-defined]

    async def testEmbedMessageGenerationError(self, handler: MessagePreprocessorHandler) -> None:
        """``generateEmbeddings`` raises → caught, logged, no crash, no DB write.

        Args:
            handler: Preprocessor fixture.
        """
        mockModel = Mock()
        mockModel.generateEmbeddings = AsyncMock(side_effect=RuntimeError("API down"))
        handler.llmService.getLLMManager().getModel = Mock(return_value=mockModel)  # type: ignore[attr-defined]

        # Should not raise.
        await self._runHelper(handler, modelName="text-embedding-3-small")

        handler.db.chatEmbeddings.saveMessageEmbedding.assert_not_called()  # type: ignore[attr-defined]

    async def testEmbedMessageSuccess(self, handler: MessagePreprocessorHandler) -> None:
        """Happy path → ``saveMessageEmbedding`` invoked with model + vector.

        Args:
            handler: Preprocessor fixture.
        """
        mockModel = Mock()
        mockModel.generateEmbeddings = AsyncMock(return_value=[0.1, 0.2, 0.3, 0.4])
        handler.llmService.getLLMManager().getModel = Mock(return_value=mockModel)  # type: ignore[attr-defined]

        await self._runHelper(handler, modelName="text-embedding-3-small")

        handler.db.chatEmbeddings.saveMessageEmbedding.assert_awaited_once()  # type: ignore[attr-defined]
        callKwargs = handler.db.chatEmbeddings.saveMessageEmbedding.await_args.kwargs  # type: ignore[attr-defined]
        assert callKwargs["chatId"] == 100
        assert callKwargs["messageId"] == MessageId(42)
        assert callKwargs["embedding"] == [0.1, 0.2, 0.3, 0.4]
        assert callKwargs["model"] == "text-embedding-3-small"

    async def testDispatchBlockNeverCrashes(self, handler: MessagePreprocessorHandler) -> None:
        """``addBackgroundTask`` raising inside the dispatch block → NEXT is still returned.

        The entire dispatch is wrapped in ``except Exception`` so the message
        pipeline must never see an embedding-dispatch failure as an error.

        Args:
            handler: Preprocessor fixture.
        """
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_defaultChatSettings(embeddingModel="text-embedding-3-small")
        )
        handler.queueService.addBackgroundTask = AsyncMock(
            side_effect=RuntimeError("queue down")
        )  # type: ignore[method-assign]
        ensured = _makeEnsuredMessage(messageText="meaningful text")

        result = await handler.newMessageHandler(ensured, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
