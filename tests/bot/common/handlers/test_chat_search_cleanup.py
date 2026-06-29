"""Tests for obsolete-embedding cleanup in :meth:`ChatSearchHandler._dtCronJob`.

Covers the cleanup path refactored to delegate to
``ChatEmbeddingsRepository.deleteObsoleteModelEmbeddings``: when a chat's
embedding model changes, the CRON job calls the repository method (which
removes stale rows from both ``message_embeddings`` and the
``vec_message_embeddings_{N}`` virtual tables). Cleanup is gated by an
in-memory tracker (``_embeddingModelTracker``) so it only fires once per
model switch — subsequent ticks with the same model are no-ops.

Repo-level concerns (vector search availability, ``listTables`` support,
provider-fetch failures) are exercised at the repository level and are
out of scope here; these tests focus on the handler's tracking and
delegation contract.
"""

from typing import Dict, Optional, Tuple
from unittest.mock import AsyncMock, Mock

from internal.bot.common.handlers.chat_search import ChatSearchHandler
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
)
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeConfigManager() -> Mock:
    """Build a minimal ``ConfigManager`` stub for the handler constructor.

    Returns:
        ``Mock`` exposing ``getBotConfig`` and ``getSearchHistoryConfig``
        with deterministic return values sufficient for construction.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test", "owners": []})
    cm.getSearchHistoryConfig = Mock(
        return_value={
            "enabled": True,
            "defaults": {"max-results": 10, "default-days": 30},
        }
    )
    return cm


def _makeChatSettings(*, embeddingModel: str = "embed-v1") -> ChatSettingsDict:
    """Build a chat-settings dict pre-populated for the backfill path.

    Args:
        embeddingModel: Value for ``EMBEDDING_MODEL`` (default
            ``"embed-v1"``). Tests that exercise the cleanup path use a
            non-empty model name so the tick reaches the cleanup block.

    Returns:
        Mapping of every :class:`ChatSettingsKey` the cron job reads.
    """
    return {
        ChatSettingsKey.REGENERATE_EMBEDDINGS: ChatSettingsValue("true"),
        ChatSettingsKey.EMBEDDING_MODEL: ChatSettingsValue(embeddingModel),
        ChatSettingsKey.LLM_RATELIMITER: ChatSettingsValue(""),
        ChatSettingsKey.ALLOW_TOOLS_COMMANDS: ChatSettingsValue("true"),
        ChatSettingsKey.EMBEDDINGS_ENABLED: ChatSettingsValue("true"),
    }


def _makeModelMock(*, embeddingDimensions: Optional[int] = None) -> Mock:
    """Build a mock embedding model for the LLM manager registry.

    Args:
        embeddingDimensions: When not ``None``, the mock exposes an
            ``embeddingDimensions`` attribute (as ``FastembedModel`` does)
            so the handler's ``modelKey`` includes the dimension suffix.
            When ``None``, the attribute is explicitly set to ``None`` so
            the handler's ``getattr(model, "embeddingDimensions", None)``
            returns ``None`` and ``modelKey`` falls back to ``modelName``
            alone. (``Mock`` auto-creates attribute access as child mocks,
            so an unset attribute would return a truthy Mock — we pin it
            to ``None`` to mirror a real model that lacks dims.)

    Returns:
        ``Mock`` with ``supportsEmbedding = True`` and an
        ``embeddingDimensions`` attribute set to ``embeddingDimensions``.
    """
    mockModel = Mock()
    mockModel.supportsEmbedding = True
    mockModel.embeddingDimensions = embeddingDimensions
    mockModel.getDimensions = AsyncMock(return_value=embeddingDimensions)
    return mockModel


def _makeHandler(
    *,
    chatSettings: Optional[ChatSettingsDict] = None,
    enabledChats: Optional[Dict[int, str]] = None,
    model: Optional[Mock] = None,
) -> Tuple[ChatSearchHandler, Dict[str, Mock]]:
    """Construct a :class:`ChatSearchHandler` wired for the cleanup tests.

    Args:
        chatSettings: Chat-settings dict returned by ``getChatSettings``.
            Defaults to :func:`_makeChatSettings`.
        enabledChats: Chat-discovery result (``chatId -> raw value``)
            returned by ``listChatsBySetting``. Defaults to a single
            enabled chat (id 100) so the round-robin pick is deterministic.
        model: Mock embedding model returned by the LLM manager. Defaults
            to a model without ``embeddingDimensions`` (mirrors a plain
            OpenAI-style embedding model).

    Returns:
        Tuple ``(handler, mocks)`` where ``mocks`` exposes the ``db`` and
        ``chatEmbeddings`` mocks for direct assertion.
    """
    cm = _makeConfigManager()
    db = Mock()
    db.chatSearch = Mock()
    db.chatSettings = Mock()
    db.chatSettings.listChatsBySetting = AsyncMock(
        return_value=enabledChats if enabledChats is not None else {100: "true"}
    )
    db.manager = Mock()
    # The cleanup path now delegates entirely to the repository method;
    # the handler never touches the SQL provider directly. ``manager`` is
    # kept on the mock so stray attribute access during construction does
    # not raise, but no provider mock is wired here.
    db.chatEmbeddings = Mock()
    db.chatEmbeddings.deleteObsoleteModelEmbeddings = AsyncMock(return_value=True)
    # The backfill batch fetch is stubbed to return an empty list so the
    # tick ends immediately after the cleanup block — tests focus on the
    # cleanup delegation, not the embed loop.
    db.chatEmbeddings.getMessagesWithoutEmbeddings = AsyncMock(return_value=[])

    handler = ChatSearchHandler(
        configManager=cm,
        database=db,
        botProvider=BotProvider.TELEGRAM,
    )

    cs = chatSettings if chatSettings is not None else _makeChatSettings()
    handler.getChatSettings = AsyncMock(return_value=cs)  # type: ignore[method-assign]

    mockModel = model if model is not None else _makeModelMock()
    llmManager = Mock(getModel=Mock(return_value=mockModel))
    handler.llmService.getLLMManager = Mock(return_value=llmManager)  # type: ignore[method-assign]

    mocks: Dict[str, Mock] = {"db": db, "chatEmbeddings": db.chatEmbeddings}
    return handler, mocks


async def _runCron(handler: ChatSearchHandler) -> None:
    """Invoke ``_dtCronJob`` once with a minimal CRON_JOB task.

    Args:
        handler: Handler under test.
    """
    await handler._dtCronJob(
        DelayedTask(
            taskId=f"cron-{id(handler)}",
            delayedUntil=0.0,
            function=DelayedTaskFunction.CRON_JOB,
            kwargs={},
        )
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestModelChangeCleanup:
    """Tests for obsolete-embedding cleanup delegation in ``_dtCronJob``."""

    async def test_cleanupDelegatesToRepositoryOnModelChange(self) -> None:
        """First tick calls ``deleteObsoleteModelEmbeddings`` with the chat's model.

        On the first tick for a chat the in-memory tracker is empty, so the
        model is treated as "changed" and the handler delegates cleanup to
        ``ChatEmbeddingsRepository.deleteObsoleteModelEmbeddings`` with the
        resolved ``chatId`` and ``currentModel``.
        """
        handler, mocks = _makeHandler()
        await _runCron(handler)

        mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.assert_awaited_once_with(
            chatId=100,
            currentModel="embed-v1",
            currentDimensions=None,
        )

    async def test_cleanupUsesChatEmbeddingModelSetting(self) -> None:
        """The ``currentModel`` argument comes from the chat's ``EMBEDDING_MODEL``.

        A chat configured with ``embed-v2`` must pass ``embed-v2`` as the
        ``currentModel`` argument — not the default or a hardcoded value.
        This is the contract that makes the cleanup correct: rows whose
        ``model`` column differs from the chat's current model are removed.
        """
        handler, mocks = _makeHandler(
            chatSettings=_makeChatSettings(embeddingModel="embed-v2"),
        )
        await _runCron(handler)

        mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.assert_awaited_once_with(
            chatId=100,
            currentModel="embed-v2",
            currentDimensions=None,
        )

    async def test_cleanupScopedToCurrentChat(self) -> None:
        """The ``chatId`` argument matches the chat picked by round-robin.

        The backfill tick picks the only enabled chat (here ``999``).
        The cleanup call must scope to that same chat so it never touches
        another chat's embeddings.
        """
        handler, mocks = _makeHandler(enabledChats={999: "true"})
        await _runCron(handler)

        mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.assert_awaited_once_with(
            chatId=999,
            currentModel="embed-v1",
            currentDimensions=None,
        )

    async def test_cleanupNoopWhenModelUnchanged(self) -> None:
        """A second tick with the same model does NOT call cleanup again.

        The in-memory tracker records the model after the first cleanup.
        On subsequent ticks with the same model the tracker value matches
        ``modelKey`` and the cleanup call is skipped entirely — no
        redundant work on every CRON tick.
        """
        handler, mocks = _makeHandler()
        await _runCron(handler)
        # First tick fired cleanup once.
        assert mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.await_count == 1

        await _runCron(handler)
        # Second tick: model unchanged → tracker matches → cleanup skipped.
        assert mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.await_count == 1

    async def test_cleanupFiresAgainWhenModelChanges(self) -> None:
        """A model swap between ticks re-triggers cleanup exactly once per change.

        Tick 1 with ``embed-v1`` fires cleanup and records the model. Tick 2
        switches the chat's ``EMBEDDING_MODEL`` to ``embed-v2``: the tracker
        value (``embed-v1``) no longer matches, so cleanup fires again and
        the tracker is updated. Tick 3 with the same ``embed-v2`` is a
        no-op.
        """
        handler, mocks = _makeHandler(
            chatSettings=_makeChatSettings(embeddingModel="embed-v1"),
        )
        await _runCron(handler)
        assert mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.await_count == 1

        # Switch the chat's embedding model and run another tick.
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_makeChatSettings(embeddingModel="embed-v2"),
        )
        await _runCron(handler)
        assert mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.await_count == 2
        mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.assert_awaited_with(
            chatId=100,
            currentModel="embed-v2",
            currentDimensions=None,
        )

        # Third tick: model unchanged again → no-op.
        await _runCron(handler)
        assert mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.await_count == 2

    async def test_modelKeyIncludesDimensionsWhenAvailable(self) -> None:
        """A dimension change (same model name) re-triggers cleanup.

        ``FastembedModel`` exposes ``embeddingDimensions``. The handler's
        ``modelKey`` is ``"modelName:dimensions"`` for such models, so
        switching from a 384-dim to a 1024-dim variant of the same model
        name is detected as a model change — even though ``modelName``
        is identical. Without the dimension suffix the handler would
        skip cleanup and leave 1024-dim embeddings alongside stale
        384-dim rows in vec0 tables.
        """
        # Tick 1: 384-dim model.
        handler, mocks = _makeHandler(
            model=_makeModelMock(embeddingDimensions=384),
        )
        await _runCron(handler)
        assert mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.await_count == 1
        # ``currentModel`` is always the bare model name (the repo matches
        # on the ``model`` column); the dimension suffix lives only in the
        # in-memory tracker. ``currentDimensions`` is forwarded so the
        # repository can delete rows whose model name matches but whose
        # ``dimensions`` column reflects the previous configuration.
        mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.assert_awaited_with(
            chatId=100,
            currentModel="embed-v1",
            currentDimensions=384,
        )

        # Tick 2: same model name, different dimensions (e.g. config swap
        # to a higher-dim variant). Cleanup must re-fire.
        llmManager = Mock(getModel=Mock(return_value=_makeModelMock(embeddingDimensions=1024)))
        handler.llmService.getLLMManager = Mock(return_value=llmManager)  # type: ignore[method-assign]
        await _runCron(handler)
        assert mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.await_count == 2
        mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.assert_awaited_with(
            chatId=100,
            currentModel="embed-v1",
            currentDimensions=1024,
        )

        # Tick 3: same model + same dimensions → no-op.
        await _runCron(handler)
        assert mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.await_count == 2

    async def test_cleanupTrackerPersistsAcrossTicksPerChat(self) -> None:
        """Tracker state survives across ticks for the same chat instance.

        Verifies the ``_embeddingModelTracker`` dict is an instance
        attribute (not local to ``_dtCronJob``): the first tick records
        the model and the second tick reads it back. A fresh handler
        instance starts with an empty tracker and always fires cleanup
        on its first tick.
        """
        handler, mocks = _makeHandler()
        assert handler._embeddingModelTracker == {}

        await _runCron(handler)
        # First tick records the bare model name (no embeddingDimensions).
        assert handler._embeddingModelTracker == {100: "embed-v1"}

        # A fresh handler has no memory of the previous cleanup.
        handler2, mocks2 = _makeHandler()
        assert handler2._embeddingModelTracker == {}
        await _runCron(handler2)
        assert mocks2["chatEmbeddings"].deleteObsoleteModelEmbeddings.await_count == 1

    async def test_backfillBatchFetchAlwaysRunsAfterCleanup(self) -> None:
        """The backfill batch fetch (Gate 4) runs after the cleanup block.

        Confirms the cleanup delegation does not short-circuit the
        subsequent ``getMessagesWithoutEmbeddings`` call — even when
        cleanup fires (first tick) the embed loop's data fetch still
        proceeds.
        """
        handler, mocks = _makeHandler()
        await _runCron(handler)

        mocks["chatEmbeddings"].getMessagesWithoutEmbeddings.assert_awaited_once()

    async def test_cleanupNotCalledWhenModelMissing(self) -> None:
        """When the chat has no ``EMBEDDING_MODEL``, cleanup is never reached.

        The tick bails out at the model-resolution gate (empty
        ``EMBEDDING_MODEL``) before the cleanup block, so neither cleanup
        nor the batch fetch is invoked.
        """
        handler, mocks = _makeHandler(
            chatSettings=_makeChatSettings(embeddingModel=""),
        )
        await _runCron(handler)

        mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.assert_not_called()
        mocks["chatEmbeddings"].getMessagesWithoutEmbeddings.assert_not_called()

    async def test_cleanupNotCalledWhenModelDoesNotSupportEmbedding(self) -> None:
        """A model without embedding support never reaches the cleanup block.

        Mirrors the ``model is None or not model.supportsEmbedding`` gate:
        the tick returns early and neither cleanup nor the batch fetch runs.
        """
        nonEmbeddingModel = Mock()
        nonEmbeddingModel.supportsEmbedding = False
        handler, mocks = _makeHandler(model=nonEmbeddingModel)
        await _runCron(handler)

        mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.assert_not_called()

    async def test_trackerNotUpdatedOnCleanupFailure(self) -> None:
        """A failed cleanup leaves the tracker untouched so the next tick retries.

        When ``deleteObsoleteModelEmbeddings`` returns ``False`` (the
        repository caught and logged an internal exception), the handler
        must NOT record the new ``modelKey`` in ``_embeddingModelTracker``.
        If it did, the next tick would treat the model as "unchanged" and
        skip cleanup entirely — leaving stale rows in place until the model
        changes again or the process restarts. By withholding the tracker
        update on failure, the next CRON tick re-attempts cleanup with the
        same ``modelKey``.
        """
        # Tick 1: succeeds (default ``return_value=True``), tracker updated.
        handler, mocks = _makeHandler()
        await _runCron(handler)
        assert handler._embeddingModelTracker == {100: "embed-v1"}

        # Tick 2: switch model and make cleanup fail.
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value=_makeChatSettings(embeddingModel="embed-v2"),
        )
        mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings = AsyncMock(return_value=False)
        await _runCron(handler)

        # Tracker retains the first key — never updated to ``embed-v2``.
        assert handler._embeddingModelTracker == {100: "embed-v1"}
        # Cleanup was attempted (and failed), so the call count advanced.
        assert mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.await_count == 1

        # Tick 3: same ``embed-v2`` model. Because the tracker still holds
        # ``embed-v1``, cleanup is retried — this is the recovery path.
        mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings = AsyncMock(return_value=True)
        await _runCron(handler)
        assert handler._embeddingModelTracker == {100: "embed-v2"}
        assert mocks["chatEmbeddings"].deleteObsoleteModelEmbeddings.await_count == 1
