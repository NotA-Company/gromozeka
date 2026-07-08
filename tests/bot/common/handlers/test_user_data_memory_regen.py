"""Tests for memory-embedding regeneration in :meth:`UserDataHandler._dtCronJob`.

Covers the Phase 3b regeneration mechanism (see
docs/plans/user-memories-v1.md §5.6, §13 Phase 3, §14.7), which mirrors the
chat-history backfill cron (``ChatSearchHandler._dtCronJob`` at
``chat_search.py:284-445``) adapted for the ``user_memories`` store.

The handler under test is :class:`UserDataHandler`; the regeneration logic
lives in :meth:`UserDataHandler._runMemoryEmbeddingRegen`, invoked once per
60s CRON_JOB tick independently of the refinement body (shared tick, NOT
shared lock — see the plan's ``[DESIGN CHOICE]`` in §5.6).

These tests focus on the handler's discovery / gating / cleanup-tracking /
re-embed-loop contract. Repository-level concerns (vec0 availability,
``listTables`` support, provider failures) are exercised at the repository
level (``tests/database/repositories/test_user_memories.py``) and are out of
scope here — the DB is a ``Mock`` and the repository methods are stubbed with
``AsyncMock`` (mirrors ``tests/bot/common/handlers/test_chat_search_cleanup.py``).
"""

from typing import Dict, Generator, List, Optional, Tuple
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.user_data import (
    MEMORY_BACKFILL_DEFAULT_BATCH_SIZE,
    MEMORY_BACKFILL_INTER_MESSAGE_DELAY_SECS,
    UserDataHandler,
)
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
)
from internal.database.models import MemoryType, UserMemorySource
from internal.database.repositories.user_memories import UserMemoryDict
from internal.services.cache import CacheService
from internal.services.queue_service.service import QueueService
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction

# ---------------------------------------------------------------------------
# Singleton hygiene
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _resetCacheServiceSingleton() -> Generator[None, None, None]:
    """Reset ``CacheService`` / ``QueueService`` singletons around every test.

    ``BaseBotHandler.__init__`` fetches both singletons; without a reset the
    ``CRON_JOB`` handler registrations accumulate across tests and a closed
    in-memory database from a previous module would leak in. Mirrors the
    autouse fixture in ``tests/bot/common/handlers/test_user_data.py``.

    Yields:
        None (autouse — no return value).
    """
    CacheService._instance = None
    QueueService._instance = None
    yield
    CacheService._instance = None
    QueueService._instance = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeConfigManager(*, enabled: bool = True, reindexBatchSize: Optional[int] = None) -> Mock:
    """Build a ``ConfigManager`` stub for the handler constructor.

    ``UserDataHandler.__init__`` reads ``getBotConfig()`` (via
    ``BaseBotHandler``) and ``get("user-memory", {})`` to cache the
    refinement + regen config. When ``enabled`` is true the constructor also
    registers the three user-memory LLM tools (against the real
    ``LLMService`` singleton reset by the autouse conftest fixture).

    Args:
        enabled: Value for ``[user-memory].enabled`` (global kill switch
            for refinement AND regeneration). Default ``True`` so the cron
            path runs.
        reindexBatchSize: Optional override for
            ``[user-memory.thresholds].memory-reindex-batch-size``. When
            ``None`` the key is omitted and the handler falls back to
            ``MEMORY_BACKFILL_DEFAULT_BATCH_SIZE``.

    Returns:
        ``Mock`` exposing ``getBotConfig`` and ``get`` with deterministic
        return values sufficient for construction.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test_token", "owners": [123456]})
    userMemoryConfig: Dict[str, object] = {"enabled": enabled}
    if reindexBatchSize is not None:
        userMemoryConfig["thresholds"] = {"memory-reindex-batch-size": reindexBatchSize}
    cm.get = Mock(return_value=userMemoryConfig)
    return cm


def _makeChatSettings(
    *,
    embeddingModel: str = "embed-v1",
    memoryEmbeddingsEnabled: bool = True,
    memoryRegenerateEmbeddings: bool = True,
) -> ChatSettingsDict:
    """Build a chat-settings dict pre-populated for the regen path.

    Args:
        embeddingModel: Value for ``EMBEDDING_MODEL`` (default ``"embed-v1"``).
            The handler treats an empty string as "no model configured" and
            bails before cleanup / re-embed.
        memoryEmbeddingsEnabled: Value for ``MEMORY_EMBEDDINGS_ENABLED``
            (the discovery flag). Default ``True``.
        memoryRegenerateEmbeddings: Value for ``MEMORY_REGENERATE_EMBEDDINGS``
            (the per-chat gate). Default ``True``.

    Returns:
        Mapping of every :class:`ChatSettingsKey` the regen path reads.
    """
    return {
        ChatSettingsKey.MEMORY_EMBEDDINGS_ENABLED: ChatSettingsValue("true" if memoryEmbeddingsEnabled else "false"),
        ChatSettingsKey.MEMORY_REGENERATE_EMBEDDINGS: ChatSettingsValue(
            "true" if memoryRegenerateEmbeddings else "false"
        ),
        ChatSettingsKey.EMBEDDING_MODEL: ChatSettingsValue(embeddingModel),
    }


def _makeModelMock(*, dimensions: Optional[int] = None, supportsEmbedding: bool = True) -> Mock:
    """Build a mock embedding model for the LLM manager registry.

    Args:
        dimensions: When not ``None``, ``getDimensions`` returns this int so
            the handler's ``modelKey`` includes the dimension suffix. When
            ``None``, ``getDimensions`` returns ``None`` and ``modelKey``
            falls back to the bare model name (mirrors a plain OpenAI-style
            embedding model).
        supportsEmbedding: Value for the ``supportsEmbedding`` property.

    Returns:
        ``Mock`` with ``supportsEmbedding`` and an async ``getDimensions``.
    """
    mockModel = Mock()
    mockModel.supportsEmbedding = supportsEmbedding
    mockModel.getDimensions = AsyncMock(return_value=dimensions)
    mockModel.generateEmbeddings = AsyncMock(return_value=[0.1, 0.2, 0.3])
    return mockModel


def _makeMemoryDict(
    *,
    memoryId: str = "mem-1",
    content: str = "likes coffee",
    userId: int = 7,
    chatId: int = 100,
) -> UserMemoryDict:
    """Build a ``UserMemoryDict``-shaped row for the re-embed loop tests.

    Args:
        memoryId: Value for ``memory_id``.
        content: Value for ``content`` (the text re-embedded).
        userId: Value for ``user_id`` (forwarded to ``saveMemoryEmbedding``).
        chatId: Value for ``chat_id``.

    Returns:
        A ``UserMemoryDict`` with sensible defaults for every required key.
    """
    now = Mock()  # exact value irrelevant; the regen loop only reads user_id/memory_id/content
    return {
        "chat_id": chatId,
        "user_id": userId,
        "thread_id": 0,
        "memory_id": memoryId,
        "type": MemoryType.FACT,
        "content": content,
        "tags": [],
        "permanent": False,
        "source": UserMemorySource.CHAT,
        "embedding_model": None,
        "embedding_dimensions": None,
        "created_at": now,
        "updated_at": now,
    }


def _makeHandler(
    *,
    enabled: bool = True,
    reindexBatchSize: Optional[int] = None,
    chatSettings: Optional[ChatSettingsDict] = None,
    enabledChats: Optional[Dict[int, str]] = None,
    model: Optional[Mock] = None,
    staleMemories: Optional[List[UserMemoryDict]] = None,
    cleanupResult: int = 0,
) -> Tuple[UserDataHandler, Dict[str, Mock]]:
    """Construct a :class:`UserDataHandler` wired for the regen tests.

    The DB is a ``Mock`` whose ``chatSettings`` / ``userMemories``
    sub-attributes are stubbed with ``AsyncMock`` so the regen path can be
    driven deterministically without touching SQLite or vec0. The handler's
    ``getChatSettings`` and ``llmService.getLLMManager`` are overridden at
    the instance level (mirrors ``test_chat_search_cleanup.py``).

    Args:
        enabled: Value for ``[user-memory].enabled``. Default ``True``.
        reindexBatchSize: Optional ``memory-reindex-batch-size`` override.
        chatSettings: Chat-settings dict returned by ``getChatSettings``.
            Defaults to :func:`_makeChatSettings`.
        enabledChats: Chat-discovery result (``chatId -> raw value``)
            returned by ``listChatsBySetting``. Defaults to a single enabled
            chat (id 100) so the round-robin pick is deterministic.
        model: Mock embedding model returned by the LLM manager. Defaults
            to a model without dimensions (mirrors a plain OpenAI-style model).
        staleMemories: Result of ``getMemoriesWithoutEmbeddings``. Defaults
            to an empty list so tests focusing on discovery / gating / cleanup
            end immediately after the cleanup block.
        cleanupResult: Return value of ``deleteObsoleteMemoryEmbeddings``
            (int reset-count). Default ``0``.

    Returns:
        Tuple ``(handler, mocks)`` where ``mocks`` exposes the ``db`` and
        ``userMemories`` / ``chatSettings`` mocks for direct assertion.
    """
    cm = _makeConfigManager(enabled=enabled, reindexBatchSize=reindexBatchSize)
    db = Mock()
    db.manager = Mock()
    db.chatSettings = Mock()
    db.chatSettings.listChatsBySetting = AsyncMock(
        return_value=enabledChats if enabledChats is not None else {100: "true"}
    )
    db.userMemories = Mock()
    db.userMemories.deleteObsoleteMemoryEmbeddings = AsyncMock(return_value=cleanupResult)
    db.userMemories.getMemoriesWithoutEmbeddings = AsyncMock(
        return_value=staleMemories if staleMemories is not None else []
    )
    # ``saveMemoryEmbedding`` is called by the regen re-embed loop; default to success.
    db.userMemories.saveMemoryEmbedding = AsyncMock(return_value=True)

    handler = UserDataHandler(
        configManager=cm,
        database=db,
        botProvider=BotProvider.TELEGRAM,
    )

    cs = chatSettings if chatSettings is not None else _makeChatSettings()
    handler.getChatSettings = AsyncMock(return_value=cs)  # type: ignore[method-assign]

    mockModel = model if model is not None else _makeModelMock()
    # Mock ``resolveModel`` directly (bypasses the module-level ``_llmManager``
    # cache in ``chat_settings.toModel``) and ``generateEmbedding`` (the re-embed
    # entry point). Tests may override either per-case.
    handler.llmService.resolveModel = Mock(return_value=mockModel)  # type: ignore[method-assign]
    handler.llmService.generateEmbedding = AsyncMock(  # type: ignore[method-assign]
        return_value=("embed-v1", [0.1, 0.2, 0.3])
    )

    mocks: Dict[str, Mock] = {
        "db": db,
        "userMemories": db.userMemories,
        "chatSettings": db.chatSettings,
        "model": mockModel,
    }
    return handler, mocks


def _makeDelayedTask() -> DelayedTask:
    """Build a minimal ``CRON_JOB`` :class:`DelayedTask` for ``_dtCronJob``.

    Returns:
        A ``DelayedTask`` whose payload is unused by the cron handler.
    """
    return DelayedTask(
        taskId="cron-test",
        delayedUntil=0.0,
        function=DelayedTaskFunction.CRON_JOB,
        kwargs={},
    )


async def _runRegen(handler: UserDataHandler) -> None:
    """Invoke ``_runMemoryEmbeddingRegen`` once.

    Args:
        handler: Handler under test.
    """
    await handler._runMemoryEmbeddingRegen()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestRegenDiscovery:
    """Tests for chat discovery + round-robin in ``_runMemoryEmbeddingRegen``."""

    async def test_globalKillSwitchBlocksRegen(self) -> None:
        """``[user-memory].enabled = false`` → ``_dtCronJob`` bails before regen.

        The global kill switch is checked at the top of ``_dtCronJob``;
        when it is off, neither regeneration nor refinement runs, and the
        discovery query is never issued.
        """
        handler, mocks = _makeHandler(enabled=False)
        await handler._dtCronJob(task=_makeDelayedTask())  # type: ignore[attr-defined]

        mocks["chatSettings"].listChatsBySetting.assert_not_called()

    async def test_regenRunsViaCronWhenEnabled(self) -> None:
        """``[user-memory].enabled = true`` → ``_dtCronJob`` invokes regen.

        Verifies the wiring: the regeneration pass is called from within
        ``_dtCronJob`` (not just callable directly). The discovery query
        targets ``MEMORY_EMBEDDINGS_ENABLED`` specifically.
        """
        handler, mocks = _makeHandler(enabled=True)
        await handler._dtCronJob(task=_makeDelayedTask())  # type: ignore[attr-defined]

        mocks["chatSettings"].listChatsBySetting.assert_awaited_once_with(key=ChatSettingsKey.MEMORY_EMBEDDINGS_ENABLED)

    async def test_discoveryUsesMemoryEmbeddingsEnabledKey(self) -> None:
        """The discovery query targets ``MEMORY_EMBEDDINGS_ENABLED`` (not ``EMBEDDINGS_ENABLED``).

        This is the key distinction from the chat-history backfill cron
        (which queries ``EMBEDDINGS_ENABLED``). Memory regen has its own
        per-feature discovery flag so a chat can enable message search
        without opting into memory re-embedding.
        """
        handler, mocks = _makeHandler()
        await _runRegen(handler)

        mocks["chatSettings"].listChatsBySetting.assert_awaited_once_with(key=ChatSettingsKey.MEMORY_EMBEDDINGS_ENABLED)

    async def test_noEnabledChatsIsNoop(self) -> None:
        """An empty discovery result short-circuits before cleanup / re-embed."""
        handler, mocks = _makeHandler(enabledChats={})
        await _runRegen(handler)

        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_not_called()
        mocks["userMemories"].getMemoriesWithoutEmbeddings.assert_not_called()

    async def test_chatsWithFlagOffAreSkipped(self) -> None:
        """Discovery filters values through ``ChatSettingsValue.toBool``.

        A chat whose ``MEMORY_EMBEDDINGS_ENABLED`` value is ``"false"`` (or
        any falsy string) is dropped from the round-robin pool. Only chats
        with a truthy value are scanned.
        """
        handler, mocks = _makeHandler(enabledChats={100: "true", 200: "false", 300: "0"})
        await _runRegen(handler)

        # Only chat 100 survived the toBool filter → it was the one scanned.
        getArgs = mocks["userMemories"].getMemoriesWithoutEmbeddings.call_args.args
        assert getArgs[0] == 100

    async def test_roundRobinPicksNextChatEachTick(self) -> None:
        """Subsequent ticks pick the next enabled chat in stable (sorted) order.

        With two enabled chats (100, 200) the first tick picks 100 and the
        second picks 200. The index survives across ticks on the same
        handler instance (``_memoryBackfillIndex`` is an instance attr).
        """
        handler, mocks = _makeHandler(enabledChats={200: "true", 100: "true"})
        await _runRegen(handler)
        firstChat = mocks["userMemories"].getMemoriesWithoutEmbeddings.call_args.args[0]
        assert firstChat == 100

        await _runRegen(handler)
        secondChat = mocks["userMemories"].getMemoriesWithoutEmbeddings.call_args.args[0]
        assert secondChat == 200


# ---------------------------------------------------------------------------
# Per-chat gate + model resolution
# ---------------------------------------------------------------------------


class TestRegenGate:
    """Tests for the per-chat gate and embedding-model resolution."""

    async def test_skipsWhenRegenerateFlagFalse(self) -> None:
        """``MEMORY_REGENERATE_EMBEDDINGS=false`` → regen skips that chat.

        The per-chat gate is checked AFTER the round-robin pick (so the
        index still advances) but BEFORE cleanup / re-embed — a chat that
        paused regeneration is not touched.
        """
        handler, mocks = _makeHandler(
            chatSettings=_makeChatSettings(memoryRegenerateEmbeddings=False),
        )
        await _runRegen(handler)

        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_not_called()
        mocks["userMemories"].getMemoriesWithoutEmbeddings.assert_not_called()

    async def test_skipsWhenEmbeddingModelMissing(self) -> None:
        """An empty ``EMBEDDING_MODEL`` causes ``resolveModel`` to raise before cleanup / re-embed.

        ``resolveModel`` delegates to ``ChatSettingsValue.toModel()`` which raises
        ``ValueError`` when the model name is empty or unknown. The exception
        propagates out of ``_runMemoryEmbeddingRegen`` (caught by the
        ``_dtCronJob`` wrapper in production). The contract under test: cleanup
        and re-embed are never reached.
        """
        handler, mocks = _makeHandler(
            chatSettings=_makeChatSettings(embeddingModel=""),
        )
        handler.llmService.resolveModel = Mock(side_effect=ValueError("Model not found"))  # type: ignore[method-assign]
        with pytest.raises(ValueError):
            await _runRegen(handler)

        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_not_called()
        mocks["userMemories"].getMemoriesWithoutEmbeddings.assert_not_called()

    async def test_skipsWhenModelNotRegistered(self) -> None:
        """An unknown ``EMBEDDING_MODEL`` raises before cleanup / re-embed.

        ``resolveModel`` → ``toModel()`` raises ``ValueError`` when the model
        is not found in the LLM manager. The exception propagates out of
        ``_runMemoryEmbeddingRegen`` (caught by ``_dtCronJob`` in production).
        """
        handler, mocks = _makeHandler()
        handler.llmService.resolveModel = Mock(side_effect=ValueError("Model not found"))  # type: ignore[method-assign]
        with pytest.raises(ValueError):
            await _runRegen(handler)

        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_not_called()
        mocks["userMemories"].getMemoriesWithoutEmbeddings.assert_not_called()


# ---------------------------------------------------------------------------
# Stale cleanup (model-drift detection)
# ---------------------------------------------------------------------------


class TestRegenCleanup:
    """Tests for obsolete-embedding cleanup delegation + tracker semantics."""

    async def test_cleanupFiresOnFirstTickForChat(self) -> None:
        """First tick for a chat: tracker empty → treated as model change → cleanup fires.

        Delegates to ``deleteObsoleteMemoryEmbeddings`` with the resolved
        ``chatId``, ``currentModel`` (from ``EMBEDDING_MODEL``), and
        ``currentDimensions`` (from ``model.getDimensions()``).
        """
        handler, mocks = _makeHandler()
        await _runRegen(handler)

        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_awaited_once_with(
            chatId=100,
            currentModel="embed-v1",
            currentDimensions=None,
        )

    async def test_cleanupUsesChatEmbeddingModelSetting(self) -> None:
        """``currentModel`` comes from the chat's ``EMBEDDING_MODEL`` setting."""
        handler, mocks = _makeHandler(
            chatSettings=_makeChatSettings(embeddingModel="embed-v2"),
        )
        await _runRegen(handler)

        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_awaited_once_with(
            chatId=100,
            currentModel="embed-v2",
            currentDimensions=None,
        )

    async def test_cleanupScopedToPickedChat(self) -> None:
        """The ``chatId`` argument matches the chat picked by round-robin."""
        handler, mocks = _makeHandler(enabledChats={999: "true"})
        await _runRegen(handler)

        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_awaited_once_with(
            chatId=999,
            currentModel="embed-v1",
            currentDimensions=None,
        )

    async def test_cleanupNoopWhenModelUnchanged(self) -> None:
        """A second tick with the same model does NOT call cleanup again.

        The tracker records the model after the first cleanup; subsequent
        ticks with the same ``modelKey`` skip cleanup entirely.
        """
        handler, mocks = _makeHandler()
        assert handler._memoryEmbeddingModelTracker == {}

        await _runRegen(handler)
        assert mocks["userMemories"].deleteObsoleteMemoryEmbeddings.await_count == 1
        assert handler._memoryEmbeddingModelTracker == {100: "embed-v1"}

        await _runRegen(handler)
        assert mocks["userMemories"].deleteObsoleteMemoryEmbeddings.await_count == 1

    async def test_cleanupFiresAgainWhenModelChanges(self) -> None:
        """A model swap between ticks re-triggers cleanup exactly once per change."""
        handler, mocks = _makeHandler(
            chatSettings=_makeChatSettings(embeddingModel="embed-v1"),
        )
        await _runRegen(handler)
        assert mocks["userMemories"].deleteObsoleteMemoryEmbeddings.await_count == 1

        # Switch the chat's embedding model and run another tick.
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_makeChatSettings(embeddingModel="embed-v2"),
        )
        await _runRegen(handler)
        assert mocks["userMemories"].deleteObsoleteMemoryEmbeddings.await_count == 2
        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_awaited_with(
            chatId=100,
            currentModel="embed-v2",
            currentDimensions=None,
        )
        assert handler._memoryEmbeddingModelTracker == {100: "embed-v2"}

        # Third tick: model unchanged again → no-op.
        await _runRegen(handler)
        assert mocks["userMemories"].deleteObsoleteMemoryEmbeddings.await_count == 2

    async def test_modelKeyIncludesDimensionsWhenAvailable(self) -> None:
        """A dimension change (same model name) re-triggers cleanup.

        ``modelKey`` is ``"modelName:dimensions"`` for models that expose
        dimensions, so switching from a 384-dim to a 1024-dim variant of
        the same model name is detected as a model change. ``currentModel``
        is always the bare model name; the dimension suffix lives only in
        the in-memory tracker. ``currentDimensions`` is forwarded so the
        repository can delete rows whose model name matches but whose
        ``embedding_dimensions`` reflects the previous configuration.
        """
        # Tick 1: 384-dim model.
        handler, mocks = _makeHandler(model=_makeModelMock(dimensions=384))
        await _runRegen(handler)
        assert mocks["userMemories"].deleteObsoleteMemoryEmbeddings.await_count == 1
        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_awaited_with(
            chatId=100,
            currentModel="embed-v1",
            currentDimensions=384,
        )
        assert handler._memoryEmbeddingModelTracker == {100: "embed-v1:384"}

        # Tick 2: same model name, different dimensions → cleanup re-fires.
        handler.llmService.resolveModel = Mock(  # type: ignore[method-assign]
            return_value=_makeModelMock(dimensions=1024),
        )
        await _runRegen(handler)
        assert mocks["userMemories"].deleteObsoleteMemoryEmbeddings.await_count == 2
        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_awaited_with(
            chatId=100,
            currentModel="embed-v1",
            currentDimensions=1024,
        )
        assert handler._memoryEmbeddingModelTracker == {100: "embed-v1:1024"}

        # Tick 3: same model + same dimensions → no-op.
        await _runRegen(handler)
        assert mocks["userMemories"].deleteObsoleteMemoryEmbeddings.await_count == 2

    async def test_batchFetchAlwaysRunsAfterCleanup(self) -> None:
        """The stale-detection fetch runs after the cleanup block.

        Confirms cleanup delegation does not short-circuit the subsequent
        ``getMemoriesWithoutEmbeddings`` call — even when cleanup fires
        (first tick) the embed loop's data fetch still proceeds.
        """
        handler, mocks = _makeHandler()
        await _runRegen(handler)

        mocks["userMemories"].getMemoriesWithoutEmbeddings.assert_awaited_once()

    async def test_cleanupNotReachedWhenModelMissing(self) -> None:
        """When the chat has no ``EMBEDDING_MODEL``, cleanup is never reached.

        ``resolveModel`` raises ``ValueError`` (empty model → not found); the
        exception fires before the cleanup block. Caught by ``_dtCronJob``
        in production.
        """
        handler, mocks = _makeHandler(
            chatSettings=_makeChatSettings(embeddingModel=""),
        )
        handler.llmService.resolveModel = Mock(side_effect=ValueError("Model not found"))  # type: ignore[method-assign]
        with pytest.raises(ValueError):
            await _runRegen(handler)

        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_not_called()
        mocks["userMemories"].getMemoriesWithoutEmbeddings.assert_not_called()


# ---------------------------------------------------------------------------
# Re-embed loop
# ---------------------------------------------------------------------------


class TestRegenReEmbedLoop:
    """Tests for the stale-memory re-embed loop."""

    async def test_staleMemoriesAreReEmbedded(self) -> None:
        """Each stale memory is re-embedded via ``generateEmbedding`` + ``saveMemoryEmbedding``.

        Verifies ``generateEmbedding`` is called with the memory's ``content``
        and the chat's ``chatId``, and ``saveMemoryEmbedding`` is called with
        the memory's ``user_id`` / ``memory_id`` and the resolved
        ``embeddingModel`` / ``embedding``. Also verifies the batch fetch
        forwarded the configured model as ``modelName`` (so rows embedded
        under a previous model are re-surfaced).
        """
        stale = [
            _makeMemoryDict(memoryId="m1", content="likes coffee", userId=7),
            _makeMemoryDict(memoryId="m2", content="speaks French", userId=8),
        ]
        handler, mocks = _makeHandler(staleMemories=stale)

        await _runRegen(handler)

        # The batch fetch forwarded modelName so model-swap rows resurface.
        getKwargs = mocks["userMemories"].getMemoriesWithoutEmbeddings.call_args.kwargs
        assert getKwargs["modelName"] == "embed-v1"
        # Each memory was re-embedded.
        assert handler.llmService.generateEmbedding.await_count == 2  # type: ignore[attr-defined]
        firstEmbedCall = handler.llmService.generateEmbedding.await_args_list[0]  # type: ignore[attr-defined]
        assert firstEmbedCall.args[0] == "likes coffee"
        assert firstEmbedCall.kwargs["chatId"] == 100
        # The save call carries the right user/memory ids and model name.
        assert mocks["userMemories"].saveMemoryEmbedding.await_count == 2
        firstSaveCall = mocks["userMemories"].saveMemoryEmbedding.await_args_list[0].kwargs
        assert firstSaveCall["chatId"] == 100
        assert firstSaveCall["embeddingModel"] == "embed-v1"
        assert firstSaveCall["memoryId"] == "m1"
        assert firstSaveCall["userId"] == 7

    async def test_batchSizeRespected(self) -> None:
        """The configured ``memory-reindex-batch-size`` is forwarded as the fetch limit.

        A custom batch size overrides ``MEMORY_BACKFILL_DEFAULT_BATCH_SIZE``.
        """
        handler, mocks = _makeHandler(reindexBatchSize=7)
        await _runRegen(handler)

        getKwargs = mocks["userMemories"].getMemoriesWithoutEmbeddings.call_args.kwargs
        assert getKwargs["limit"] == 7

    async def test_batchSizeDefaultsToConstant(self) -> None:
        """Without an explicit config key, the default constant is used."""
        assert MEMORY_BACKFILL_DEFAULT_BATCH_SIZE == 50
        handler, mocks = _makeHandler()
        await _runRegen(handler)

        getKwargs = mocks["userMemories"].getMemoriesWithoutEmbeddings.call_args.kwargs
        assert getKwargs["limit"] == MEMORY_BACKFILL_DEFAULT_BATCH_SIZE

    async def test_interMessageDelayApplied(self) -> None:
        """``asyncio.sleep`` is called once per memory with the configured delay.

        The inter-call cushion keeps the asyncio loop responsive between
        embedding API calls (mirrors ``BACKFILL_INTER_MESSAGE_DELAY_SECS``
        in ``chat_search.py``).
        """
        stale = [_makeMemoryDict(memoryId=f"m{i}") for i in range(3)]
        handler, _mocks = _makeHandler(staleMemories=stale)
        with patch(
            "internal.bot.common.handlers.user_data.asyncio.sleep",
            new=AsyncMock(),
        ) as sleepMock:
            await _runRegen(handler)

        assert sleepMock.await_count == 3
        # Every sleep uses the configured delay constant.
        for call in sleepMock.await_args_list:
            assert call.args == (MEMORY_BACKFILL_INTER_MESSAGE_DELAY_SECS,)

    async def test_noStaleMemoriesIsNoop(self) -> None:
        """An empty stale-detection result → no re-embed calls."""
        handler, mocks = _makeHandler(staleMemories=[])
        await _runRegen(handler)

        handler.llmService.generateEmbedding.assert_not_called()  # type: ignore[attr-defined]

    async def test_perMemoryErrorDoesNotAbortBatch(self) -> None:
        """A single failed re-embed never aborts the rest of the batch.

        ``generateEmbedding`` returning ``None`` (embedding failure) causes
        the loop to skip ``saveMemoryEmbedding`` for that memory but continue
        with the remaining ones. The successful row is still saved.
        """
        stale = [
            _makeMemoryDict(memoryId="bad", content="will fail"),
            _makeMemoryDict(memoryId="good", content="will succeed"),
        ]
        handler, mocks = _makeHandler(staleMemories=stale)
        # First call returns None (embedding failure), second returns a valid tuple.
        handler.llmService.generateEmbedding = AsyncMock(  # type: ignore[method-assign]
            side_effect=[None, ("embed-v1", [0.1, 0.2, 0.3])],
        )
        await _runRegen(handler)

        # Both memories were attempted.
        assert handler.llmService.generateEmbedding.await_count == 2  # type: ignore[attr-defined]
        # Only the successful one was saved.
        assert mocks["userMemories"].saveMemoryEmbedding.await_count == 1

    async def test_logsInfoWhenMemoriesEmbedded(self) -> None:
        """A successful batch logs an info line with the embedded count.

        Guards the ``embedded > 0`` info-log branch (which also exercises
        ``utils.now()`` elapsed-time computation).
        """
        stale = [_makeMemoryDict(memoryId="m1")]
        handler, _mocks = _makeHandler(staleMemories=stale)
        await _runRegen(handler)
        # No assertion on the log text itself (logger is not captured); the
        # test guards the branch executing without raising.


# ---------------------------------------------------------------------------
# Never-crash contract (defensive exception guards)
# ---------------------------------------------------------------------------


class TestRegenNeverCrash:
    """Tests for the three ``except Exception`` never-crash guards in regen.

    ``_runMemoryEmbeddingRegen`` wraps its discovery / settings-read / stale-
    fetch in defensive ``try/except Exception`` blocks so a transient DB
    failure never crashes the shared 60s cron tick. Each test forces one
    branch to raise and asserts the method returns without raising AND that
    no downstream step (cleanup / fetch / re-embed) is reached.
    """

    async def test_listChatsBySettingErrorReturnsEarly(self) -> None:
        """A raise in ``listChatsBySetting`` is swallowed → early return.

        The discovery query is the first guarded block; on failure the method
        logs-and-returns so a DB hiccup never propagates to ``_dtCronJob``.
        None of the downstream steps (cleanup, stale fetch, re-embed) may run.
        """
        handler, mocks = _makeHandler()
        mocks["chatSettings"].listChatsBySetting = AsyncMock(side_effect=RuntimeError("db down"))
        await _runRegen(handler)  # must not raise

        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_not_called()
        mocks["userMemories"].getMemoriesWithoutEmbeddings.assert_not_called()
        handler.llmService.generateEmbedding.assert_not_called()  # type: ignore[attr-defined]

    async def test_getChatSettingsErrorReturnsEarly(self) -> None:
        """A raise in ``getChatSettings`` is swallowed → early return.

        The per-chat settings read is guarded after the round-robin pick; on
        failure the method logs-and-returns so this chat is skipped without
        reaching cleanup / stale fetch / re-embed.
        """
        handler, mocks = _makeHandler()
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("settings read failed"),
        )
        await _runRegen(handler)  # must not raise

        mocks["userMemories"].deleteObsoleteMemoryEmbeddings.assert_not_called()
        mocks["userMemories"].getMemoriesWithoutEmbeddings.assert_not_called()
        handler.llmService.generateEmbedding.assert_not_called()  # type: ignore[attr-defined]

    async def test_getMemoriesWithoutEmbeddingsErrorReturnsEarly(self) -> None:
        """A raise in ``getMemoriesWithoutEmbeddings`` is swallowed → no re-embed.

        The stale-detection fetch is the third guarded block; on failure the
        method logs-and-returns. Cleanup (``deleteObsoleteMemoryEmbeddings``)
        runs BEFORE the fetch and therefore HAS already executed by the time
        the fetch raises — the contract under test here is only that the
        re-embed loop is never reached (no ``generateEmbedding`` calls).
        """
        handler, mocks = _makeHandler()
        mocks["userMemories"].getMemoriesWithoutEmbeddings = AsyncMock(side_effect=RuntimeError("fetch failed"))
        await _runRegen(handler)  # must not raise

        handler.llmService.generateEmbedding.assert_not_called()  # type: ignore[attr-defined]
