"""Tests for :class:`UserMemoriesHandler` (memory-refinement + user-memory tools).

Phase 7a/7b — deterministic refinement-loop behaviours:

* ``(B)`` ``newMessageHandler`` increments the per-``(chatId, userId, threadId)``
  ``_accounting`` counter and returns ``NEXT`` when
  ``ChatSettingsKey.MEMORY_REFINEMENT_ENABLED`` is on.
* ``(C)`` ``newMessageHandler`` leaves ``_accounting`` untouched when the feature
  is disabled.

Phase 7b — the CRON refinement loop (``_dtCronJob`` / ``_runSingleRefinement``) with
``LLMService.generateTextViaLLM`` mocked per-handler-instance:

* ``(F)`` ``_dtCronJob`` early-returns when ``[user-memory].enabled`` is false.
* ``(G)`` ``_dtCronJob`` early-returns when ``_refineLock`` is already held.
* ``(H)`` ``_dtCronJob`` dispatches refinement for a due (count-threshold) entry,
  resets its counter, and persists the summary + cursors.
* ``(I)`` ``_runSingleRefinement`` bails when fewer than ``min-messages`` are available.
* ``(J)`` ``_dtCronJob`` dispatches a never-refined (TS=0) user due-by-time even
  when its new-message counter is below ``min-messages``; ``_runSingleRefinement``
  then pulls lifetime history, bails on too few messages, and advances the
  in-memory ``_lastRefinedTS`` so the user is not retried every tick.
* ``(K)`` ``_dtCronJob`` uses the credit-consumed counter reset: increments that
  arrive during the (slow) LLM call are preserved, not zeroed (follow-up #1).

Phase 2 — the three user-memory LLM tools (``add_memory`` / ``delete_memory`` /
``search_memories``) with dedup state machine (see
docs/plans/user-memories-v1.md §8.3-8.5, §14.2). The ``db.userMemories``
repository is replaced with a ``Mock`` per test, and the embedding model is
stubbed on the shared ``LLMService`` singleton so dedup search behaviour is
deterministic without hitting vec0 or a real embedding API.

The handler is constructed against a real in-memory database (``testDatabase``
fixture) and the real :class:`CacheService` singleton (reset per test by the
local autouse fixture). ``getChatSettings`` is stubbed at the instance level for
tests (B)/(C) to flip the boolean ``MEMORY_REFINEMENT_ENABLED`` flag, mirroring
the pattern used by the other handler tests under
``tests/bot/common/handlers/``.
"""

import datetime
import json
import logging
import time
import tomllib
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.base import HandlerResultStatus
from internal.bot.common.handlers.user_memories import UserMemoriesHandler
from internal.bot.common.models import CallbackButton
from internal.bot.constants import ToolName
from internal.bot.models import (
    BotProvider,
    ButtonDataKey,
    ButtonUserDataConfigAction,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    CommandPermission,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
)
from internal.database import Database
from internal.database.models import MemoryType, UserMemorySource
from internal.database.repositories.user_memories import UserMemoriesRepository, UserMemoryDict
from internal.database.utils import DEFAULT_THREAD_ID
from internal.models import MessageId
from internal.services.cache import CacheService, UserActiveActionEnum
from internal.services.queue_service.service import QueueService
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction
from lib.ai import LLMToolCall, ModelMessage, ModelResultStatus, ModelRunResult

# ---------------------------------------------------------------------------
# Singleton hygiene
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _resetCacheServiceSingleton() -> Generator[None, None, None]:
    """Reset the ``CacheService`` and ``QueueService`` singletons around every test.

    ``tests/conftest.py`` resets ``LLMService`` / ``ProxyService`` /
    ``ProxyHelper`` autouse, but not ``CacheService`` or ``QueueService``. The
    cache singleton holds a reference to the injected database, so without a
    reset the closed in-memory database from the previous test would leak into
    the next one. The ``QueueService`` singleton accumulates ``CRON_JOB``
    handler registrations from every ``_makeHandler`` call (each constructed
    handler registers itself on the process-wide singleton), so without a reset
    those references persist across the session. Resetting both before *and*
    after each test keeps every test hermetic and prevents leakage into other
    test modules that run afterwards.

    Yields:
        None.
    """
    CacheService._instance = None
    QueueService._instance = None
    yield
    CacheService._instance = None
    QueueService._instance = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeConfigManager() -> Mock:
    """Build a minimal ``ConfigManager`` stub for the handler constructor.

    ``BaseBotHandler.__init__`` reads ``getBotConfig()``; ``UserMemoriesHandler.__init__``
    additionally reads ``get("user-memory", {})`` to cache the refinement config
    (enabled flag + thresholds). Returning ``{}`` makes every threshold fall back
    to its module constant and leaves the feature disabled — matching the
    pre-refactor behaviour for tests that don't exercise the cron path.

    Returns:
        ``Mock`` exposing ``getBotConfig()`` returning a token/owners dict and
        ``get(key, default)`` returning ``{}`` for any key.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test_token", "owners": [123456]})
    cm.get = Mock(return_value={})
    return cm


async def _makeHandler(testDatabase: Database, configManager: Optional[Mock] = None) -> UserMemoriesHandler:
    """Construct a :class:`UserMemoriesHandler` wired to a real in-memory database.

    Resets the ``CacheService`` singleton, injects *testDatabase* into it (so
    cache reads/writes round-trip through SQLite), then builds the handler.
    The handler's ``BaseBotHandler.__init__`` re-fetches the same cache
    singleton, so ``handler.cache`` is the injected instance.

    Args:
        testDatabase: Fresh in-memory :class:`Database` (``testDatabase``
            fixture).
        configManager: Optional ``ConfigManager`` stub. When omitted, the
            default :func:`_makeConfigManager` is used (no ``user-memory``
            section). Pass :func:`_makeUserMemoryConfigManager` to drive the
            memory-refinement CRON path.

    Returns:
        A fully constructed :class:`UserMemoriesHandler` whose ``cache`` is backed
        by *testDatabase*.
    """
    CacheService._instance = None
    cache = CacheService.getInstance()
    await cache.injectDatabase(testDatabase)

    handler = UserMemoriesHandler(
        configManager=configManager or _makeConfigManager(),
        database=testDatabase,
        botProvider=BotProvider.TELEGRAM,
    )
    return handler


def _makeEnsuredMessage(
    *,
    chatId: int = 100,
    userId: int = 7,
    chatType: ChatType = ChatType.PRIVATE,
    threadId: int = DEFAULT_THREAD_ID,
    messageText: str = "hello",
) -> EnsuredMessage:
    """Build a minimal real :class:`EnsuredMessage` for handler tests.

    The tool handlers' isinstance guard asserts
    ``isinstance(ensuredMessage, EnsuredMessage)``, so a real instance (not a
    ``Mock``) is required. Only ``recipient.id``, ``sender.id``, ``threadId``
    and ``recipient.chatType`` are read by the code paths under test.

    Args:
        chatId: Recipient chat id (default 100).
        userId: Sender user id (default 7).
        chatType: Recipient chat type (default ``PRIVATE``).
        threadId: Thread id stored on the message (default ``DEFAULT_THREAD_ID``).
        messageText: Message body text (default ``"hello"``).

    Returns:
        Fully constructed :class:`EnsuredMessage`.
    """
    ensuredMessage = EnsuredMessage(
        sender=MessageSender(id=userId, name="Alice", username=f"@user{userId}"),
        recipient=MessageRecipient(id=chatId, chatType=chatType),
        messageId=42,
        date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText=messageText,
    )
    ensuredMessage.threadId = threadId
    return ensuredMessage


def _chatSettings(
    *,
    memoryRefinementEnabled: bool,
    refineModel: Optional[str] = None,
    refineFallbackModel: Optional[str] = None,
) -> ChatSettingsDict:
    """Build a chat-settings dict carrying the keys the refinement path reads.

    Includes ``MEMORY_REFINEMENT_ENABLED`` (the boolean toggle read by
    ``newMessageHandler`` and ``_runSingleRefinement``), the two master gates
    (``MEMORY_ENABLED`` / ``EMBEDDINGS_ENABLED`` — both defaulting to ``"true"``
    because the rewritten gates in ``newMessageHandler``,
    ``_runMemoryRefinement``, and ``_runMemoryEmbeddingRegen`` read them via
    direct subscript), plus the two prompt settings
    (``MEMORY_REFINE_SYSTEM_PROMPT`` / ``MEMORY_REFINE_USER_PROMPT_TEMPLATE``)
    now read by ``_runSingleRefinement``. The user-prompt template MUST
    contain the ``.format()`` placeholders so the template render doesn't
    raise. Phase 4a switched the template to ``{existingMemories}`` +
    ``{messages}``; the ``{existingUserData}`` / ``{existingSummary}`` keys
    are passed as backward-compat aliases (see ``_runSingleRefinement``) so
    older per-chat overrides still format.

    When *refineModel* is provided, the ``MEMORY_REFINE_MODEL`` setting is
    populated so tests asserting the JSONL-log ``model`` field can pin it.
    When *refineFallbackModel* is provided, ``MEMORY_REFINE_FALLBACK_MODEL`` is
    populated likewise (used by the ``isFallback=True`` test to assert the
    fallback branch of ``_resolveRefineModel``).

    Args:
        memoryRefinementEnabled: Value for the refinement toggle.
        refineModel: Optional value for ``MEMORY_REFINE_MODEL`` (the primary
            refinement model id). When ``None`` the key is omitted and
            ``_resolveRefineModel`` returns ``""``.
        refineFallbackModel: Optional value for ``MEMORY_REFINE_FALLBACK_MODEL``
            (the fallback model id). When ``None`` the key is omitted.

    Returns:
        Mapping with the refinement toggle, master gates, prompt keys
        (+ optional model(s)).
    """
    settings: ChatSettingsDict = {
        ChatSettingsKey.MEMORY_REFINEMENT_ENABLED: ChatSettingsValue("true" if memoryRefinementEnabled else "false"),
        ChatSettingsKey.MEMORY_ENABLED: ChatSettingsValue("true"),
        ChatSettingsKey.EMBEDDINGS_ENABLED: ChatSettingsValue("true"),
        ChatSettingsKey.MEMORY_REFINE_SYSTEM_PROMPT: ChatSettingsValue("system prompt placeholder"),
        ChatSettingsKey.MEMORY_REFINE_USER_PROMPT_TEMPLATE: ChatSettingsValue("{existingMemories}\n{messages}"),
    }
    if refineModel is not None:
        settings[ChatSettingsKey.MEMORY_REFINE_MODEL] = ChatSettingsValue(refineModel)
    if refineFallbackModel is not None:
        settings[ChatSettingsKey.MEMORY_REFINE_FALLBACK_MODEL] = ChatSettingsValue(refineFallbackModel)
    return settings


def _stubGetChatSettings(
    handler: UserMemoriesHandler,
    *,
    memoryRefinementEnabled: bool,
    refineModel: Optional[str] = None,
    refineFallbackModel: Optional[str] = None,
) -> AsyncMock:
    """Override ``handler.getChatSettings`` with an ``AsyncMock``.

    Mirrors the instance-level stubbing pattern used by the other handler tests
    (``test_chat_search.py`` / ``test_delete_from_user.py``) so the boolean
    refinement flag can be flipped deterministically without loading real TOML
    defaults.

    Args:
        handler: Handler under test.
        memoryRefinementEnabled: Value to return for
            ``MEMORY_REFINEMENT_ENABLED``.
        refineModel: Optional value for ``MEMORY_REFINE_MODEL`` forwarded to
            :func:`_chatSettings` (used by the JSONL-log tests to assert the
            resolved model id).
        refineFallbackModel: Optional value for ``MEMORY_REFINE_FALLBACK_MODEL``
            forwarded to :func:`_chatSettings` (used by the ``isFallback=True``
            test).

    Returns:
        The installed ``AsyncMock`` (for call assertions).
    """
    getChatSettingsMock = AsyncMock(
        return_value=_chatSettings(
            memoryRefinementEnabled=memoryRefinementEnabled,
            refineModel=refineModel,
            refineFallbackModel=refineFallbackModel,
        )
    )
    handler.getChatSettings = getChatSettingsMock  # type: ignore[method-assign]
    return getChatSettingsMock


# ---------------------------------------------------------------------------
# (B) + (C) newMessageHandler accounting
# ---------------------------------------------------------------------------


class TestNewMessageHandlerAccounting:
    """Tests for the ``_accounting`` increment in :meth:`UserMemoriesHandler.newMessageHandler`.

    A non-private (group) message is used so the handler returns ``NEXT``
    immediately after the accounting block, without entering the wizard path
    (which would touch ``cache.getUserState``). The accounting block itself runs
    before the chat-type guard, so group messages are still counted.
    """

    async def test_incrementsAccountingWhenEnabled(self, testDatabase: Database) -> None:
        """Feature on → counter increments per message and handler returns ``NEXT``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)

        chatId = 200
        userId = 7
        ensuredMessage = _makeEnsuredMessage(
            chatId=chatId, userId=userId, chatType=ChatType.GROUP, threadId=DEFAULT_THREAD_ID
        )

        result = await handler.newMessageHandler(ensuredMessage, updateObj=Mock())
        assert result is HandlerResultStatus.NEXT
        assert handler._accounting[(chatId, userId, DEFAULT_THREAD_ID)] == 1  # type: ignore[attr-defined]

        # A second message for the same (chat, user, thread) bumps the count.
        resultSecond = await handler.newMessageHandler(ensuredMessage, updateObj=Mock())
        assert resultSecond is HandlerResultStatus.NEXT
        assert handler._accounting[(chatId, userId, DEFAULT_THREAD_ID)] == 2  # type: ignore[attr-defined]

    async def test_normalizesThreadIdNoneToDefault(self, testDatabase: Database) -> None:
        """``threadId=None`` normalises to ``DEFAULT_THREAD_ID`` in the accounting key.

        The handler computes its ``_accounting`` key with
        ``ensuredMessage.threadId or DEFAULT_THREAD_ID``. The default
        ``threadId=DEFAULT_THREAD_ID`` path (``0 or 0 == 0``) never exercises the
        ``None -> 0`` branch of that expression, so this test forces
        ``ensuredMessage.threadId = None`` and asserts the counter lands under
        the ``(..., 0)`` key — proving ``None`` is normalised to ``0`` rather
        than being stored verbatim (which would raise a key-collision / missing
        entry).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)

        chatId = 210
        userId = 9
        ensuredMessage = _makeEnsuredMessage(chatId=chatId, userId=userId, chatType=ChatType.GROUP)
        ensuredMessage.threadId = None

        result = await handler.newMessageHandler(ensuredMessage, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        # The None threadId must have been normalised to DEFAULT_THREAD_ID (0);
        # no entry should exist under a literal None key.
        assert handler._accounting[(chatId, userId, DEFAULT_THREAD_ID)] == 1  # type: ignore[attr-defined]
        assert (chatId, userId, None) not in handler._accounting  # type: ignore[attr-defined]

    async def test_doesNotIncrementWhenDisabled(self, testDatabase: Database) -> None:
        """Feature off → ``_accounting`` stays empty (no key created).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubGetChatSettings(handler, memoryRefinementEnabled=False)

        ensuredMessage = _makeEnsuredMessage(chatId=200, userId=7, chatType=ChatType.GROUP)

        result = await handler.newMessageHandler(ensuredMessage, updateObj=Mock())

        assert result is HandlerResultStatus.NEXT
        assert handler._accounting == {}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# In-memory chat discovery (_trackedChats) — regen-discovery rewrite
# ---------------------------------------------------------------------------


class TestTrackedChatsDiscovery:
    """Regression tests for the in-memory ``_trackedChats`` discovery mechanism.

    The DB-scan chat discovery (``ChatSettingsRepository.listChatsBySetting``)
    was replaced by an in-memory ``self._trackedChats: MutableSet[int]``
    populated by :meth:`UserMemoriesHandler.newMessageHandler` when both
    ``MEMORY_ENABLED`` and ``EMBEDDINGS_ENABLED`` are true. The cron's
    ``_runMemoryEmbeddingRegen`` round-robins over this set and self-evicts
    a chat via ``.discard()`` when the per-chat gate fails.

    These tests pin the three behavioural contracts of that rewrite: the
    add-path on both-gates-true, the skip-path on memory-disabled, and
    the eviction-path on a gate failure during regen.
    """

    async def test_newMessageHandler_addsChatWhenBothFlagsTrue(self, testDatabase: Database) -> None:
        """Both master gates true → recipient chat id added to ``_trackedChats``.

        ``newMessageHandler`` reads ``MEMORY_ENABLED`` and
        ``EMBEDDINGS_ENABLED`` via direct subscript; when both are truthy
        the recipient id is inserted into ``_trackedChats`` so the regen
        cron can discover it on the next tick.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)

        ensuredMessage = _makeEnsuredMessage(chatId=100, userId=7, chatType=ChatType.GROUP)

        await handler.newMessageHandler(ensuredMessage, updateObj=Mock())

        assert 100 in handler._trackedChats  # type: ignore[attr-defined]

    async def test_newMessageHandler_skipsWhenMemoryDisabled(self, testDatabase: Database) -> None:
        """``MEMORY_ENABLED=false`` → chat NOT added to ``_trackedChats``.

        Pins the memory branch of the ``MEMORY_ENABLED && EMBEDDINGS_ENABLED``
        add-gate: when the master memory gate is off the ``and``
        short-circuits before the ``.add()``, so the chat never enters the
        regen discovery pool even if ``EMBEDDINGS_ENABLED`` is true.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        settings = _chatSettings(memoryRefinementEnabled=True)
        settings[ChatSettingsKey.MEMORY_ENABLED] = ChatSettingsValue("false")
        handler.getChatSettings = AsyncMock(return_value=settings)  # type: ignore[method-assign]

        ensuredMessage = _makeEnsuredMessage(chatId=100, userId=7, chatType=ChatType.GROUP)

        await handler.newMessageHandler(ensuredMessage, updateObj=Mock())

        assert 100 not in handler._trackedChats  # type: ignore[attr-defined]

    async def test_newMessageHandler_skipsWhenEmbeddingsDisabled(self, testDatabase: Database) -> None:
        """``EMBEDDINGS_ENABLED=false`` (memory still on) → chat NOT added to ``_trackedChats``.

        Pins the embeddings branch of the ``MEMORY_ENABLED &&
        EMBEDDINGS_ENABLED`` add-gate: with ``MEMORY_ENABLED`` still true but
        ``EMBEDDINGS_ENABLED`` flipped false, the gate fails and the chat is
        never admitted to the regen discovery pool.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        settings = _chatSettings(memoryRefinementEnabled=True)
        settings[ChatSettingsKey.EMBEDDINGS_ENABLED] = ChatSettingsValue("false")
        handler.getChatSettings = AsyncMock(return_value=settings)  # type: ignore[method-assign]

        ensuredMessage = _makeEnsuredMessage(chatId=100, userId=7, chatType=ChatType.GROUP)

        await handler.newMessageHandler(ensuredMessage, updateObj=Mock())

        assert 100 not in handler._trackedChats  # type: ignore[attr-defined]

    async def test_runMemoryEmbeddingRegen_evictsChatOnGateFail(self, testDatabase: Database) -> None:
        """Gate failure in ``_runMemoryEmbeddingRegen`` evicts chat via ``.discard()``.

        Seeds ``_trackedChats = {100}`` with chat settings whose
        ``EMBEDDINGS_ENABLED`` is false. After one regen tick the chat
        must be removed from ``_trackedChats`` (one-way eviction via
        ``set.discard``) so it is not re-scanned on subsequent ticks until
        a new qualifying message re-adds it.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        settings = _chatSettings(memoryRefinementEnabled=True)
        settings[ChatSettingsKey.EMBEDDINGS_ENABLED] = ChatSettingsValue("false")
        handler.getChatSettings = AsyncMock(return_value=settings)  # type: ignore[method-assign]

        handler._trackedChats = {100}  # type: ignore[attr-defined]
        await handler._runMemoryEmbeddingRegen()  # type: ignore[attr-defined]

        assert 100 not in handler._trackedChats  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Phase 7b helpers — CRON refinement loop
# ---------------------------------------------------------------------------


def _makeUserMemoryConfigManager(*, enabled: bool, jsonLogging: Optional[dict] = None) -> Mock:
    """Build a ``ConfigManager`` stub returning a ``user-memory`` config dict.

    Unlike :func:`_makeConfigManager` (which leaves ``user-memory`` absent so
    the handler treats the feature as disabled), this stub makes
    ``cm.get("user-memory", {})`` return a real ``{"enabled": enabled}`` dict.
    Thresholds/prompts are deliberately omitted so the handler falls back to
    the module constants (``MEMORY_COUNT_THRESHOLD`` etc.), which match the
    real defaults in ``configs/00-defaults/user-memory.toml``.

    Args:
        enabled: Value for the ``[user-memory].enabled`` global kill switch.
        jsonLogging: Optional value for the ``[user-memory.json-logging]``
            sub-table. When ``None`` (default) the sub-table is omitted so the
            handler reads the disabled-by-default refinement-log config.

    Returns:
        ``Mock`` exposing ``getBotConfig()`` and a ``get(key, default)``
        side-effect that only answers the ``"user-memory"`` key.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test_token", "owners": [123456]})

    userMemoryConfig: dict = {"enabled": enabled}
    if jsonLogging is not None:
        userMemoryConfig["json-logging"] = jsonLogging

    def _get(key: str, default: object = None) -> object:
        """Side-effect for ``cm.get``.

        Args:
            key: Config section key.
            default: Fallback when the key is unknown.

        Returns:
            The ``user-memory`` config dict when ``key == "user-memory"``,
            otherwise *default*.
        """
        if key == "user-memory":
            return userMemoryConfig
        return default

    cm.get = Mock(side_effect=_get)
    return cm


def _makeDelayedTask() -> DelayedTask:
    """Build a minimal ``CRON_JOB`` :class:`DelayedTask` for ``_dtCronJob``.

    ``_dtCronJob`` documents its ``task`` argument as unused, so the payload is
    a throwaway placeholder only the constructor's required fields are filled.

    Returns:
        A :class:`DelayedTask` of function type ``CRON_JOB`` with empty kwargs.
    """
    return DelayedTask(
        taskId="test-cron-tick",
        delayedUntil=0.0,
        function=DelayedTaskFunction.CRON_JOB,
        kwargs={},
    )


async def _seedChatMessages(
    db: Database,
    *,
    chatId: int,
    userId: int,
    count: int,
    threadId: int = DEFAULT_THREAD_ID,
) -> None:
    """Save ``count`` plain-text chat messages for a user with incremental ids/dates.

    A ``chat_users`` row for *(chatId, userId)* must already exist —
    ``saveChatMessage`` increments ``chat_users.messages_count`` and
    ``getChatMessagesSince`` JOINs ``chat_users``, so the row is required for
    the round-trip.

    Args:
        db: Target database.
        chatId: Chat id.
        userId: Author user id.
        count: Number of messages to save.
        threadId: Thread id (default ``DEFAULT_THREAD_ID``).
    """
    base = datetime.datetime(2026, 7, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    for i in range(count):
        await db.chatMessages.saveChatMessage(
            date=base + datetime.timedelta(minutes=i),
            chatId=chatId,
            userId=userId,
            messageId=MessageId(1000 + i),
            threadId=threadId,
            messageText=f"message {i}",
        )


# ---------------------------------------------------------------------------
# (F-J) _dtCronJob / _runSingleRefinement
# ---------------------------------------------------------------------------


class TestCronJobAndRefinement:
    """Behaviour tests for the memory-refinement CRON loop and refinement logic.

    ``generateTextViaLLM`` is mocked per-handler-instance
    (``handler.llmService.generateTextViaLLM = AsyncMock(...)``) mirroring the
    pattern in ``tests/bot/common/handlers/test_dev_commands.py``. The real
    in-memory database backs the message/user/metadata reads and the summary
    persistence, so the full read-modify-write of
    ``chat_users.metadata.memoryRefinement`` is exercised end-to-end.
    """

    async def test_dtCronJobEarlyReturnsWhenDisabled(self, testDatabase: Database) -> None:
        """``[user-memory].enabled = false`` → no dispatch and counters untouched.

        Pre-seeds ``_accounting`` well over threshold, but with the global kill
        switch off ``_dtCronJob`` returns before touching the lock or the
        counter.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=False))
        mockGenerate = AsyncMock()
        handler.llmService.generateTextViaLLM = mockGenerate  # type: ignore[method-assign]

        chatId, userId, threadId = 300, 7, DEFAULT_THREAD_ID
        handler._accounting[(chatId, userId, threadId)] = 10  # type: ignore[attr-defined]

        await handler._dtCronJob(task=_makeDelayedTask())  # type: ignore[attr-defined]

        mockGenerate.assert_not_called()
        # Disabled path must not reset the counter.
        assert handler._accounting[(chatId, userId, threadId)] == 10  # type: ignore[attr-defined]

    async def test_dtCronJobEarlyReturnsWhenLockHeld(self, testDatabase: Database) -> None:
        """``_refineLock`` already held → no dispatch and counters untouched.

        With ``enabled = true`` but the lock pre-acquired (simulating an
        in-flight batch from a previous tick), ``_dtCronJob`` bails before the
        scan/dispatch block.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=True))
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)
        mockGenerate = AsyncMock()
        handler.llmService.generateTextViaLLM = mockGenerate  # type: ignore[method-assign]

        chatId, userId, threadId = 310, 8, DEFAULT_THREAD_ID
        handler._accounting[(chatId, userId, threadId)] = 10  # type: ignore[attr-defined]

        await handler._refineLock.acquire()  # type: ignore[attr-defined]
        try:
            await handler._dtCronJob(task=_makeDelayedTask())  # type: ignore[attr-defined]
            mockGenerate.assert_not_called()
            assert handler._accounting[(chatId, userId, threadId)] == 10  # type: ignore[attr-defined]
        finally:
            handler._refineLock.release()  # type: ignore[attr-defined]

    async def test_dtCronJobDispatchesRefinementAndResetsCounter(self, testDatabase: Database) -> None:
        """Count-threshold-due entry → one LLM call, counter reset, summary persisted.

        Seeds a chat_users row + 5 messages (meets ``min-messages``), sets the
        accounting counter to the count threshold (5), and asserts that after
        the tick: ``generateTextViaLLM`` was awaited once, the counter reset to
        0, and ``chat_users.metadata.memoryRefinement["0"]`` carries a fresh
        ``lastProcessedMessageDate`` cursor. Phase 4a dropped the rolling-bio
        ``summary`` from the persisted blob (memories now live in
        ``user_memories`` via the tools), so ``summary`` must NOT be present.
        The ``lastRefinedTS`` is NO LONGER persisted to the DB entry — it is
        tracked in-memory on ``handler._lastRefinedTS`` instead.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=True))
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)

        refineResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Refined summary text",
        )
        mockGenerate = AsyncMock(return_value=refineResult)
        handler.llmService.generateTextViaLLM = mockGenerate  # type: ignore[method-assign]

        chatId, userId, threadId = 320, 9, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user9", "Alice")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        handler._accounting[(chatId, userId, threadId)] = 5  # type: ignore[attr-defined]

        await handler._dtCronJob(task=_makeDelayedTask())  # type: ignore[attr-defined]

        mockGenerate.assert_awaited_once()
        # The dispatch loop's `finally` runs the credit-consumed reset:
        # ``max(0, current - preCount)``. With preCount == current (5), the
        # result is 0 and the key is DROPPED (``pop``-on-zero keeps the dict
        # free of empty entries so they aren't re-iterated). ``.get(..., 0)``
        # covers both the popped-key and set-to-0 shapes.
        assert handler._accounting.get((chatId, userId, threadId), 0) == 0  # type: ignore[attr-defined]

        userInfo = await testDatabase.chatUsers.getChatUser(chatId=chatId, userId=userId)
        metadata = handler.parseUserMetadata(userInfo)
        entry = metadata.get("memoryRefinement", {}).get(str(threadId))
        assert entry is not None
        # Phase 4a: the rolling-bio ``summary`` is no longer persisted — only
        # the cursor survives. Memories live in ``user_memories`` via the tools.
        assert "summary" not in entry
        # lastRefinedTS is NO LONGER persisted to the DB entry (moved in-memory).
        assert "lastRefinedTS" not in entry
        # Instead it is tracked in handler._lastRefinedTS.
        lastRefined = handler._lastRefinedTS.get((chatId, userId, threadId))  # type: ignore[attr-defined]
        assert isinstance(lastRefined, int)
        assert abs(int(time.time()) - lastRefined) < 10
        # _runSingleRefinement persists the refinement cursor from the NEWEST message
        # of the batch: lastProcessedMessageDate = newest["date"].isoformat()
        # and lastProcessedMessageId = newest["message_id"].asStr(), where
        # ``newest`` is ``messages[0]`` of the DESC-ordered
        # getChatMessagesSince result (ORDER BY c.date DESC, c.message_id DESC).
        # _seedChatMessages writes 5 messages starting at 2026-07-01T12:00:00
        # UTC with ids MessageId(1000+i); the newest is index 4, i.e.
        # 2026-07-01T12:04:00+00:00 / MessageId(1004). Pinning the exact values
        # catches cursor-drift regressions (e.g. accidentally using the oldest
        # message, or a different attribute path).
        assert entry.get("lastProcessedMessageDate") == "2026-07-01T12:04:00+00:00"
        assert entry.get("lastProcessedMessageId") == "1004"

    async def test_runSingleRefinementBailsWhenFewerThanMinMessages(self, testDatabase: Database) -> None:
        """Below ``min-messages`` → ``_runSingleRefinement`` returns with no LLM call.

        Creates a chat_users row + only 2 messages (below the 5-message floor),
        then calls ``_runSingleRefinement`` directly. The LLM mock must not fire and
        no memory entry must be persisted.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=True))
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)
        mockGenerate = AsyncMock()
        handler.llmService.generateTextViaLLM = mockGenerate  # type: ignore[method-assign]

        chatId, userId, threadId = 330, 10, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user10", "Bob")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=2)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        mockGenerate.assert_not_called()
        userInfo = await testDatabase.chatUsers.getChatUser(chatId=chatId, userId=userId)
        metadata = handler.parseUserMetadata(userInfo)
        assert metadata.get("memoryRefinement", {}).get(str(threadId)) is None

    async def test_runSingleRefinementWarnsWhenRoundLimitHit(
        self, testDatabase: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A ``roundLimitHit`` result logs a memory-refinement warning.

        Gate-2 Decision 1(d): the maxRounds cap is otherwise silent — the LLM
        returns what looks like a successful (but incomplete) curation. The
        handler must detect ``result.roundLimitHit`` and emit a warning so
        incomplete batches are visible in logs. Drives ``_runSingleRefinement``
        directly with ``generateTextViaLLM`` mocked to return a FINAL result
        carrying ``roundLimitHit=True``.

        Args:
            testDatabase: Fresh in-memory database fixture.
            caplog: pytest log-capture fixture.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=True))
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)

        refineResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="partially curated",
        )
        refineResult.roundLimitHit = True
        mockGenerate = AsyncMock(return_value=refineResult)
        handler.llmService.generateTextViaLLM = mockGenerate  # type: ignore[method-assign]

        chatId, userId, threadId = 360, 13, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user13", "Eve")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        with caplog.at_level(logging.WARNING, logger="internal.bot.common.handlers.user_memories"):
            await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        # The cap-hit warning specific to memory refinement is emitted.
        assert any(
            rec.levelno == logging.WARNING and "maxRounds cap" in rec.message and "incomplete" in rec.message
            for rec in caplog.records
        )

    async def test_dtCronJobDispatchesNeverRefinedUserWhoBailsOnTooFewLifetimeMessages(
        self, testDatabase: Database
    ) -> None:
        """Never-refined user with too few lifetime messages → dispatched, bails once, TS advances.

        Post-refactor behaviour: the scan loop no longer pre-skips never-refined
        users whose *new-message* counter is below ``min-messages``. That skip
        was over-conservative — refinement of a never-refined user actually pulls
        *lifetime* history via ``getChatMessagesSince(sinceDateTime=None)``, so a
        user with plenty of pre-existing chat history but few messages since the
        feature was enabled was wrongly blocked from ever getting an initial
        summary.

        A never-refined user (``_lastRefinedTS`` absent → TS=0) is therefore
        due-by-time (``elapsed = now - 0`` far exceeds the 6h threshold) and
        enters the due list. ``_runSingleRefinement`` then fetches the lifetime
        messages; if fewer than ``min-messages`` (5) exist it bails — BUT
        advances the in-memory ``_lastRefinedTS`` to ``now`` so the user is not
        re-scanned and re-bailed on every 60s tick (the count threshold still
        fires independently once messages pile up). The dispatch ``finally``
        then runs the credit-consumed counter reset, consuming the pre-count
        (3) and dropping the now-zero key.

        Setup: never-refined user, counter = 3 (< count threshold 5), only 2
        lifetime messages (< ``min-messages`` 5). After the tick the LLM mock
        must NOT have been called (bail happens before the LLM call), the
        counter must be consumed to 0 (key popped, since 3 − 3 = 0),
        ``_lastRefinedTS[key]`` must be a recent int (bail-path reset), and no
        memory entry must be persisted (bail returns before
        ``_persistMemoryEntry``).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=True))
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)
        mockGenerate = AsyncMock()
        handler.llmService.generateTextViaLLM = mockGenerate  # type: ignore[method-assign]

        chatId, userId, threadId = 340, 11, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user11", "Carol")
        # Fewer than min-messages (5) LIFETIME messages → _runSingleRefinement bails.
        # count (2) is deliberately distinct from the counter value (3) below so
        # the two magnitudes can't be confused in a failure trace.
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=2)

        key = (chatId, userId, threadId)
        handler._accounting[key] = 3  # type: ignore[attr-defined]

        await handler._dtCronJob(task=_makeDelayedTask())  # type: ignore[attr-defined]

        # Bail path returns before the LLM call.
        mockGenerate.assert_not_called()
        # Credit-consumed reset in the dispatch `finally`: preCount (3) is
        # subtracted from the current count (3); the resulting 0 DROPS the key
        # (``pop`` keeps the dict free of empty entries so they aren't
        # re-iterated). ``.get(..., 0)`` covers both the popped-key and
        # set-to-0 shapes — the counter is fully consumed, NOT preserved at 3.
        assert handler._accounting.get(key, 0) == 0  # type: ignore[attr-defined]
        # The bail path advances the in-memory TS so the user is not retried
        # every 60s tick: the time threshold won't fire again until 6h elapse,
        # and only the count threshold can re-arm refinement earlier.
        lastRefined = handler._lastRefinedTS.get(key)  # type: ignore[attr-defined]
        assert isinstance(lastRefined, int)
        assert abs(int(time.time()) - lastRefined) < 10
        # No memory entry persisted — the bail returns before _persistMemoryEntry.
        userInfo = await testDatabase.chatUsers.getChatUser(chatId=chatId, userId=userId)
        metadata = handler.parseUserMetadata(userInfo)
        assert metadata.get("memoryRefinement", {}).get(str(threadId)) is None

    async def test_counterResetPreservesIncrementsDuringLlmCall(self, testDatabase: Database) -> None:
        """Credit-consumed counter reset: increments during the LLM call survive.

        Regression test for the counter-reset race (follow-up #1). The OLD code
        did ``self._accounting[key] = 0`` in the ``finally`` block of the
        dispatch loop, which wiped any increments from messages that arrived
        during the (possibly multi-second) LLM call. The NEW code subtracts only
        the count captured at scan time (``preCount``), preserving the delta.

        Setup: pre-seed the counter to 5 (meets the count threshold), then mock
        ``generateTextViaLLM`` with an async side-effect that bumps the counter
        by 3 mid-call (simulating 3 new messages arriving). After the tick, the
        counter must be 3 (8 − 5 = 3 preserved), NOT 0.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=True))
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)

        chatId, userId, threadId = 350, 12, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user12", "Dave")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        # Pre-seed the counter to the count threshold (5).
        handler._accounting[(chatId, userId, threadId)] = 5  # type: ignore[attr-defined]

        async def simulateArrivalDuringLlmCall(**kwargs: object) -> ModelRunResult:
            """Async side-effect that bumps the counter before returning.

            Simulates 3 messages arriving during the LLM call, then returns the
            mocked refinement result.

            Args:
                **kwargs: Ignored kwargs from generateTextViaLLM.

            Returns:
                ModelRunResult: A final-result carrying the new summary text.
            """
            handler._accounting[(chatId, userId, threadId)] += 3  # type: ignore[attr-defined]
            return ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="summary")

        mockGenerate = AsyncMock(side_effect=simulateArrivalDuringLlmCall)
        handler.llmService.generateTextViaLLM = mockGenerate  # type: ignore[method-assign]

        await handler._dtCronJob(task=_makeDelayedTask())  # type: ignore[attr-defined]

        mockGenerate.assert_awaited_once()
        # 8 total (5 pre-seeded + 3 during call) − 5 consumed = 3 preserved.
        assert handler._accounting[(chatId, userId, threadId)] == 3  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# JSONL refinement logging
# ---------------------------------------------------------------------------


class TestRefinementJsonLog:
    """Tests for the per-run JSONL refinement log (``_writeRefinementJsonLog``).

    Mirrors the established ``AbstractModel.printJSONLog`` shape: a guarded,
    synchronous append of one JSON object per line. The hook fires from
    ``_runSingleRefinement`` after the LLM call succeeds and before the empty-summary
    early-return, so both populated and empty summaries are logged.

    Each test drives a real ``_runSingleRefinement`` against the in-memory database
    with ``generateTextViaLLM`` mocked, then reads back the JSONL file written
    under the pytest ``tmp_path`` fixture (never the real ``logs/`` dir).
    """

    async def test_refinementJsonLogDisabledByDefault(self, testDatabase: Database, tmp_path: Path) -> None:
        """No ``json-logging`` sub-table → no log file is written.

        Exercises the true omitted-default path: the handler's
        ``userMemoryConfig.get("json-logging", {})`` returns ``{}``, so
        ``_refineLogEnabled`` is False. Runs a full refinement and asserts no
        ``refine.jsonl*`` file was created.

        Args:
            testDatabase: Fresh in-memory database fixture.
            tmp_path: Per-test temporary directory.
        """
        handler = await _makeHandler(
            testDatabase,
            configManager=_makeUserMemoryConfigManager(enabled=True, jsonLogging=None),
        )
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="Refined summary text")
        )

        chatId, userId, threadId = 361, 13, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user13", "Erin")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        # No dated-suffix variant either — glob covers refine.jsonl and refine.jsonl.YYYY-MM-DD.
        assert list(tmp_path.glob("refine.jsonl*")) == []

    async def test_refinementJsonLogDisabledWhenExplicitlyConfigured(
        self, testDatabase: Database, tmp_path: Path
    ) -> None:
        """``json-logging.enabled = false`` → no log file is written.

        Constructs the handler with refinement enabled but the json-logging
        sub-table explicitly disabling the log, runs a full refinement, and
        asserts no ``refine.jsonl*`` file was created.

        Args:
            testDatabase: Fresh in-memory database fixture.
            tmp_path: Per-test temporary directory for the (unused) log file.
        """
        refineLogFile = str(tmp_path / "refine.jsonl")
        handler = await _makeHandler(
            testDatabase,
            configManager=_makeUserMemoryConfigManager(
                enabled=True,
                jsonLogging={"enabled": False, "file": refineLogFile, "add-date-suffix": False},
            ),
        )
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="Refined summary text")
        )

        chatId, userId, threadId = 360, 13, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user13", "Erin")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        # No dated-suffix variant either — glob covers refine.jsonl and refine.jsonl.YYYY-MM-DD.
        assert list(tmp_path.glob("refine.jsonl*")) == []

    async def test_refinementJsonLogWritesAllFields(self, testDatabase: Database, tmp_path: Path) -> None:
        """Successful refinement → exactly one JSONL line with all 12 fields.

        Seeds 5 messages (ids 1000..1004, newest=1004), runs ``_runSingleRefinement``
        with a mocked non-fallback result, and asserts the written JSONL line
        carries every field with the expected value, including the Phase 4a
        per-tool counts (``addCount``/``deleteCount``/``searchCount``). The
        mocked result has no ``toolUsageHistory`` → all three counts are 0.

        Args:
            testDatabase: Fresh in-memory database fixture.
            tmp_path: Per-test temporary directory for the JSONL log file.
        """
        refineLogFile = str(tmp_path / "refine.jsonl")
        handler = await _makeHandler(
            testDatabase,
            configManager=_makeUserMemoryConfigManager(
                enabled=True,
                jsonLogging={"enabled": True, "file": refineLogFile, "add-date-suffix": False},
            ),
        )
        refineModel = "test-refine-model"
        _stubGetChatSettings(handler, memoryRefinementEnabled=True, refineModel=refineModel)
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(
                rawResult={},
                status=ModelResultStatus.FINAL,
                resultText="Refined summary text",
                elapsedTime=1.5,
            )
        )

        chatId, userId, threadId = 370, 14, DEFAULT_THREAD_ID
        login = "@user14"
        await testDatabase.chatUsers.updateChatUser(chatId, userId, login, "Frank")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        entries = _readRefineLog(tmp_path / "refine.jsonl")
        assert len(entries) == 1
        entry = entries[0]
        assert entry["chatId"] == chatId
        assert entry["userId"] == userId
        assert entry["threadId"] == threadId
        assert entry["login"] == login
        assert entry["messagesCount"] == 5
        # messages are DESC by date then message_id → [0]=newest=1004, [-1]=oldest=1000.
        assert entry["firstMessageId"] == "1000"
        assert entry["lastMessageId"] == "1004"
        assert entry["summary"] == "Refined summary text"
        # Phase 4a: per-tool counts derived from ``result.toolUsageHistory``.
        # The mocked result has no tool history → all three counts are 0.
        assert entry["addCount"] == 0
        assert entry["deleteCount"] == 0
        assert entry["searchCount"] == 0
        # ``date`` is present and ISO-parseable.
        datetime.datetime.fromisoformat(entry["date"])

    async def test_refinementJsonLogWritesEmptySummary(self, testDatabase: Database, tmp_path: Path) -> None:
        """Empty summary → JSONL line is still written with ``summary == ""``.

        The hook is placed before the cursor persist, so an empty result must
        still be logged. Phase 4a removed the empty-summary early-return: the
        cursor now advances regardless (the LLM persisted memories via tools),
        so the ``memoryRefinement`` entry is written with the cursor but NO
        ``summary`` key.

        Args:
            testDatabase: Fresh in-memory database fixture.
            tmp_path: Per-test temporary directory for the JSONL log file.
        """
        refineLogFile = str(tmp_path / "refine.jsonl")
        handler = await _makeHandler(
            testDatabase,
            configManager=_makeUserMemoryConfigManager(
                enabled=True,
                jsonLogging={"enabled": True, "file": refineLogFile, "add-date-suffix": False},
            ),
        )
        _stubGetChatSettings(handler, memoryRefinementEnabled=True, refineModel="test-refine-model")
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="")
        )

        chatId, userId, threadId = 380, 15, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user15", "Grace")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        entries = _readRefineLog(tmp_path / "refine.jsonl")
        assert len(entries) == 1
        assert entries[0]["summary"] == ""
        assert entries[0]["chatId"] == chatId
        assert entries[0]["userId"] == userId
        # Phase 4a: no early-return on empty summary → cursor IS persisted, but
        # the ``summary`` key is absent from the blob.
        userInfo = await testDatabase.chatUsers.getChatUser(chatId=chatId, userId=userId)
        metadata = handler.parseUserMetadata(userInfo)
        entry = metadata.get("memoryRefinement", {}).get(str(threadId))
        assert entry is not None
        assert "summary" not in entry
        assert entry.get("lastProcessedMessageId") == "1004"

    async def test_refinementJsonLogUsesFallbackModelWhenIsFallback(
        self, testDatabase: Database, tmp_path: Path
    ) -> None:
        """``result.isFallback == True`` → fallback model id is logged, not the primary.

        ``_resolveRefineModel`` branches on ``result.isFallback``: when True it
        resolves ``MEMORY_REFINE_FALLBACK_MODEL``, otherwise
        ``MEMORY_REFINE_MODEL``. All other tests use the default
        ``isFallback=False``; this test sets both model settings to distinct
        values, marks the mocked result as a fallback via ``setFallback(True)``,
        and asserts the JSONL ``model`` field equals the fallback id.

        Args:
            testDatabase: Fresh in-memory database fixture.
            tmp_path: Per-test temporary directory for the JSONL log file.
        """
        refineLogFile = str(tmp_path / "refine.jsonl")
        handler = await _makeHandler(
            testDatabase,
            configManager=_makeUserMemoryConfigManager(
                enabled=True,
                jsonLogging={"enabled": True, "file": refineLogFile, "add-date-suffix": False},
            ),
        )
        primaryModel = "test-refine-model"
        fallbackModel = "test-fallback-model"
        _stubGetChatSettings(
            handler,
            memoryRefinementEnabled=True,
            refineModel=primaryModel,
            refineFallbackModel=fallbackModel,
        )
        fallbackResult = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Refined summary text",
        )
        fallbackResult.setFallback(True)
        handler.llmService.generateTextViaLLM = AsyncMock(return_value=fallbackResult)  # type: ignore[method-assign]

        chatId, userId, threadId = 390, 16, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user16", "Heidi")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        entries = _readRefineLog(tmp_path / "refine.jsonl")
        assert len(entries) == 1

    async def test_refinementJsonLogWithDateSuffix(self, testDatabase: Database, tmp_path: Path) -> None:
        """``add-date-suffix = true`` → dated file ``refine.jsonl.YYYY-MM-DD`` is written.

        All other tests pass ``add-date-suffix: False``. This test enables the
        suffix, runs a refinement, and asserts exactly one file matching
        ``refine.jsonl.*`` exists with today's UTC date as the suffix, and that
        the file contains a valid JSONL line with the expected fields. The
        expected suffix is computed the same way the writer computes it
        (``datetime.datetime.now(tz=datetime.timezone.utc)``) to avoid
        timezone flakiness.

        Args:
            testDatabase: Fresh in-memory database fixture.
            tmp_path: Per-test temporary directory for the JSONL log file.
        """
        refineLogFile = str(tmp_path / "refine.jsonl")
        handler = await _makeHandler(
            testDatabase,
            configManager=_makeUserMemoryConfigManager(
                enabled=True,
                jsonLogging={"enabled": True, "file": refineLogFile, "add-date-suffix": True},
            ),
        )
        refineModel = "test-refine-model"
        _stubGetChatSettings(handler, memoryRefinementEnabled=True, refineModel=refineModel)
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="Refined summary text")
        )

        chatId, userId, threadId = 400, 17, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user17", "Ivan")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        # The suffix uses UTC, same as the writer — compute it identically here.
        expectedSuffix = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        datedFiles = list(tmp_path.glob("refine.jsonl.*"))
        assert len(datedFiles) == 1
        assert datedFiles[0].name == f"refine.jsonl.{expectedSuffix}"

        entries = _readRefineLog(datedFiles[0])
        assert len(entries) == 1
        assert entries[0]["chatId"] == chatId
        assert entries[0]["userId"] == userId
        assert entries[0]["summary"] == "Refined summary text"


def _readRefineLog(path: Path) -> List[Dict[str, Any]]:
    """Read a JSONL refinement log and return one parsed dict per non-empty line.

    Args:
        path: Path to the JSONL file written by ``_writeRefinementJsonLog``.

    Returns:
        List of ``json.loads``-parsed dicts, one per non-empty line.
    """
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


# ---------------------------------------------------------------------------
# Phase 4a — refinement prompt rewrite + memory pre-load + JSONL tool counts
# ---------------------------------------------------------------------------
#
# See docs/plans/user-memories-v1.md §10, §10.2(a)/(d), §13 Phase 4. The
# refinement LLM no longer produces a rolling text summary; it curates the
# ``user_memories`` store via add_memory / delete_memory / search_memories.
# ``_runSingleRefinement`` therefore: pre-loads permanent + recent memories into
# ``{existingMemories}`` (replacing the old ``{existingUserData}`` /
# ``{existingSummary}``), drops the ``summary`` from the persisted cursor
# blob, and logs per-tool counts in the JSONL line.


def _repoRoot() -> Path:
    """Return the repository root (the dir containing ``configs/``).

    Computed relative to this test file so the prompt-placeholder test can
    locate ``configs/00-defaults/bot-defaults.toml`` without depending on the
    process CWD (pytest may be invoked from anywhere).

    Returns:
        Absolute path to the repo root.
    """
    # tests/bot/common/handlers/test_user_memories.py → up 4 parents = repo root.
    return Path(__file__).resolve().parents[4]


class TestPhase4aRefinementRewrite:
    """Phase 4a — prompt rewrite, memory pre-load, dropped summary persistence.

    Each test drives a real ``_runSingleRefinement`` against the in-memory database
    with ``generateTextViaLLM`` mocked, then inspects the persisted cursor blob
    and/or the captured LLM call args.
    """

    async def test_defaultPromptTemplateUsesNewPlaceholders(self) -> None:
        """The TOML default user-prompt template carries the Phase-4a placeholders.

        Parses ``configs/00-defaults/bot-defaults.toml`` and asserts the
        ``memory-refine-user-prompt-template`` value contains
        ``{existingMemories}`` and ``{messages}``, and does NOT contain the
        retired ``{existingUserData}`` / ``{existingSummary}`` placeholders.
        Catches a drift where the default is reverted to the old shape.
        """
        tomlPath = _repoRoot() / "configs" / "00-defaults" / "bot-defaults.toml"
        with open(tomlPath, "rb") as f:
            data = tomllib.load(f)
        template = data["bot"]["defaults"]["memory-refine-user-prompt-template"]
        assert "{existingMemories}" in template
        assert "{messages}" in template
        assert "{existingUserData}" not in template
        assert "{existingSummary}" not in template

    async def test_defaultSystemPromptReferencesNewTools(self) -> None:
        """The TOML default system prompt instructs the new memory tools.

        Asserts the ``memory-refine-system-prompt`` value references
        ``add_memory`` / ``delete_memory`` / ``search_memories`` and does NOT
        reference the retired ``add_user_data`` / ``delete_user_data``.
        """
        tomlPath = _repoRoot() / "configs" / "00-defaults" / "bot-defaults.toml"
        with open(tomlPath, "rb") as f:
            data = tomllib.load(f)
        prompt = data["bot"]["defaults"]["memory-refine-system-prompt"]
        assert "add_memory" in prompt
        assert "delete_memory" in prompt
        assert "search_memories" in prompt
        assert "add_user_data" not in prompt
        assert "delete_user_data" not in prompt

    async def test_runSingleRefinementPreloadsMemoriesIntoUserPrompt(self, testDatabase: Database) -> None:
        """Pre-loaded memories appear in the user prompt passed to the LLM.

        Seeds one permanent and one recent memory, runs ``_runSingleRefinement``, and
        asserts both memory contents appear in the ``messages[1].content`` (the
        user message) captured from the ``generateTextViaLLM`` call.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=True))
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="")
        )

        chatId, userId, threadId = 410, 18, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user18", "Karl")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)
        # Seed a permanent + a recent memory the pre-load should surface.
        # ``threadId`` matches how the refinement tools store memories (Amendment
        # #7: every tool-created memory is scoped to the active thread, not
        # NULL — only migration-backfilled facts carry thread_id IS NULL).
        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            "mem-perm",
            type="bio",
            content="PERMANENT_MARKER_BIO",
            tags=[],
            permanent=True,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )
        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            "mem-recent",
            type="fact",
            content="RECENT_MARKER_FACT",
            tags=[],
            permanent=False,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        sentMessages = handler.llmService.generateTextViaLLM.call_args.kwargs["messages"]  # type: ignore[attr-defined]
        userPrompt = sentMessages[1].content
        assert "PERMANENT_MARKER_BIO" in userPrompt
        assert "RECENT_MARKER_FACT" in userPrompt

    async def test_runSingleRefinementPreloadFailsGracefullyOnDbError(self, testDatabase: Database) -> None:
        """A ``getPermanentMemories`` failure does NOT abort the run.

        The pre-load is best-effort: a transient DB error yields an empty
        snapshot and the LLM simply has no prior context. The run still
        completes and the cursor still advances.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=True))
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="")
        )
        chatId, userId, threadId = 420, 19, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user19", "Lena")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        # Force the pre-load to raise. The repo uses ``__slots__ = ()`` so the
        # mocks must patch the class, not a bare instance attribute (mirrors
        # the established ``patch.object(UserMemoriesRepository, …)`` pattern).
        with (
            patch.object(UserMemoriesRepository, "getPermanentMemories", AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(UserMemoriesRepository, "getLatestMemories", AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        handler.llmService.generateTextViaLLM.assert_awaited_once()  # type: ignore[attr-defined]
        # Cursor still advances despite the pre-load failure.
        userInfo = await testDatabase.chatUsers.getChatUser(chatId=chatId, userId=userId)
        metadata = handler.parseUserMetadata(userInfo)
        assert metadata.get("memoryRefinement", {}).get(str(threadId)) is not None

    async def test_runSingleRefinementDoesNotPersistSummary(self, testDatabase: Database) -> None:
        """After a run, the cursor blob has no ``summary`` key.

        The LLM returned non-empty text, but Phase 4a dropped ``summary`` from
        the persisted blob — memories live in ``user_memories`` via the tools.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=True))
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="would-be summary")
        )

        chatId, userId, threadId = 430, 20, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user20", "Mona")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        userInfo = await testDatabase.chatUsers.getChatUser(chatId=chatId, userId=userId)
        metadata = handler.parseUserMetadata(userInfo)
        entry = metadata.get("memoryRefinement", {}).get(str(threadId))
        assert entry is not None
        assert "summary" not in entry

    async def test_runSingleRefinementCursorAdvancesToNewestMessage(self, testDatabase: Database) -> None:
        """``lastProcessedMessageDate`` is updated to the newest analyzed message.

        ``_seedChatMessages`` writes ids 1000..1004 (newest=1004). After the run
        the cursor must point at message 1004 / its date, proving the cursor
        advance logic survived the Phase 4a rewrite.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=True))
        _stubGetChatSettings(handler, memoryRefinementEnabled=True)
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="")
        )

        chatId, userId, threadId = 440, 21, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user21", "Nina")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        userInfo = await testDatabase.chatUsers.getChatUser(chatId=chatId, userId=userId)
        metadata = handler.parseUserMetadata(userInfo)
        entry = metadata.get("memoryRefinement", {}).get(str(threadId))
        assert entry is not None
        assert entry.get("lastProcessedMessageId") == "1004"
        assert entry.get("lastProcessedMessageDate") == "2026-07-01T12:04:00+00:00"

    async def test_runSingleRefinementCustomUserPromptTemplateFormats(self, testDatabase: Database) -> None:
        """A per-chat ``MEMORY_REFINE_USER_PROMPT_TEMPLATE`` override formats end-to-end.

        ``_runSingleRefinement`` calls ``userPromptTemplate.format(...)`` with only
        the Phase-4a placeholders — ``{existingMemories}`` and ``{messages}``
        (the retired ``{existingUserData}`` / ``{existingSummary}`` aliases are
        NOT passed). This test installs a custom override carrying exactly the
        supported placeholders and asserts the run completes without
        ``KeyError``. It complements
        :meth:`test_runSingleRefinementPreloadsMemoriesIntoUserPrompt` by exercising
        the config-manager-driven override path rather than the default
        template.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase, configManager=_makeUserMemoryConfigManager(enabled=True))
        # Install a custom template carrying ONLY the placeholders production passes.
        settings = _chatSettings(memoryRefinementEnabled=True)
        settings[ChatSettingsKey.MEMORY_REFINE_USER_PROMPT_TEMPLATE] = ChatSettingsValue(
            "{existingMemories}\n{messages}"
        )
        handler.getChatSettings = AsyncMock(return_value=settings)  # type: ignore[method-assign]
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="")
        )

        chatId, userId, threadId = 450, 22, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user22", "Oleg")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        # Must not raise KeyError.
        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]
        handler.llmService.generateTextViaLLM.assert_awaited_once()  # type: ignore[attr-defined]


class TestPhase4aJsonLogToolCounts:
    """Phase 4a — JSONL log records per-tool call counts from the run history.

    The counts are derived from ``result.toolUsageHistory`` (walked by
    :meth:`UserMemoriesHandler._countRefinementToolCalls`). Each test seeds a
    mocked ``ModelRunResult`` carrying assistant messages with ``toolCalls``
    and asserts the JSONL ``addCount`` / ``deleteCount`` / ``searchCount``.
    """

    @staticmethod
    def _resultWithToolHistory(toolCallsByTurn: List[List[LLMToolCall]], *, resultText: str = "") -> ModelRunResult:
        """Build a ``ModelRunResult`` whose ``toolUsageHistory`` carries the given calls.

        Args:
            toolCallsByTurn: One list of :class:`LLMToolCall` per assistant turn.
            resultText: Final-turn text (default empty).

        Returns:
            A ``ModelRunResult`` with ``toolUsageHistory`` populated.
        """
        history: List[ModelMessage] = []
        for calls in toolCallsByTurn:
            history.append(ModelMessage(role="assistant", content="", toolCalls=calls))
        return ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText=resultText,
            toolUsageHistory=history,
        )

    async def test_jsonLogRecordsToolCallCounts(self, testDatabase: Database, tmp_path: Path) -> None:
        """2 add_memory + 1 search_memories + 1 delete_memory → matching counts.

        Args:
            testDatabase: Fresh in-memory database fixture.
            tmp_path: Per-test temporary directory for the JSONL log file.
        """
        refineLogFile = str(tmp_path / "refine.jsonl")
        handler = await _makeHandler(
            testDatabase,
            configManager=_makeUserMemoryConfigManager(
                enabled=True,
                jsonLogging={"enabled": True, "file": refineLogFile, "add-date-suffix": False},
            ),
        )
        _stubGetChatSettings(handler, memoryRefinementEnabled=True, refineModel="test-refine-model")
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=self._resultWithToolHistory(
                [
                    [LLMToolCall(id="c1", name=ToolName.SEARCH_MEMORIES.value, parameters={})],
                    [
                        LLMToolCall(id="c2", name=ToolName.ADD_MEMORY.value, parameters={}),
                        LLMToolCall(id="c3", name=ToolName.ADD_MEMORY.value, parameters={}),
                        LLMToolCall(id="c4", name=ToolName.DELETE_MEMORY.value, parameters={}),
                    ],
                ]
            )
        )

        chatId, userId, threadId = 460, 23, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user23", "Pavel")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        entries = _readRefineLog(tmp_path / "refine.jsonl")
        assert len(entries) == 1
        entry = entries[0]
        assert entry["addCount"] == 2
        assert entry["searchCount"] == 1
        assert entry["deleteCount"] == 1

    async def test_jsonLogZeroCountsWhenNoToolHistory(self, testDatabase: Database, tmp_path: Path) -> None:
        """No ``toolUsageHistory`` on the result → all three counts are 0.

        Covers the single-turn / no-tools path (e.g. the LLM returned only text).

        Args:
            testDatabase: Fresh in-memory database fixture.
            tmp_path: Per-test temporary directory for the JSONL log file.
        """
        refineLogFile = str(tmp_path / "refine.jsonl")
        handler = await _makeHandler(
            testDatabase,
            configManager=_makeUserMemoryConfigManager(
                enabled=True,
                jsonLogging={"enabled": True, "file": refineLogFile, "add-date-suffix": False},
            ),
        )
        _stubGetChatSettings(handler, memoryRefinementEnabled=True, refineModel="test-refine-model")
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="plain text")
        )

        chatId, userId, threadId = 470, 24, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user24", "Rita")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        entries = _readRefineLog(tmp_path / "refine.jsonl")
        assert len(entries) == 1
        assert entries[0]["addCount"] == 0
        assert entries[0]["deleteCount"] == 0
        assert entries[0]["searchCount"] == 0

    async def test_jsonLogCountsFromFallbackToolCalls(self, testDatabase: Database, tmp_path: Path) -> None:
        """``toolUsageHistory=None`` + ``toolCalls=[...]`` → counts from the elif fallback.

        Single-turn providers populate only the final-turn ``result.toolCalls``
        (no ``toolUsageHistory``). ``_countRefinementToolCalls`` must then
        count via the ``elif result.toolCalls:`` branch instead of the history walk.

        Args:
            testDatabase: Fresh in-memory database fixture.
            tmp_path: Per-test temporary directory for the JSONL log file.
        """
        refineLogFile = str(tmp_path / "refine.jsonl")
        handler = await _makeHandler(
            testDatabase,
            configManager=_makeUserMemoryConfigManager(
                enabled=True,
                jsonLogging={"enabled": True, "file": refineLogFile, "add-date-suffix": False},
            ),
        )
        _stubGetChatSettings(handler, memoryRefinementEnabled=True, refineModel="test-refine-model")
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(
                rawResult={},
                status=ModelResultStatus.FINAL,
                resultText="",
                toolUsageHistory=None,
                toolCalls=[
                    LLMToolCall(id="c1", name=ToolName.ADD_MEMORY.value, parameters={}),
                    LLMToolCall(id="c2", name=ToolName.SEARCH_MEMORIES.value, parameters={}),
                ],
            )
        )

        chatId, userId, threadId = 480, 25, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user25", "Sven")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        entries = _readRefineLog(tmp_path / "refine.jsonl")
        assert len(entries) == 1
        entry = entries[0]
        assert entry["addCount"] == 1
        assert entry["searchCount"] == 1
        assert entry["deleteCount"] == 0

    async def test_jsonLogExcludesSynthesisedBrokenCallFromHistory(
        self, testDatabase: Database, tmp_path: Path
    ) -> None:
        """Synthesised broken-call markers in toolUsageHistory are not counted.

        Regression: when the LLM emits a broken-but-recognisable tool call, the
        LLM service synthesises a ``TOOL_CALLS`` result whose ``LLMToolCall``
        carries a non-None ``errorMessage`` and is never executed (the model is
        handed the error and retries). Counting that synthesised call would
        double-count a single logical tool use — the broken attempt plus its
        successful retry both seen as ``add_memory`` calls.

        This test seeds the history branch with one synthesised broken
        ``add_memory`` call (errorMessage set) and one real ``add_memory`` call,
        then asserts ``addCount == 1`` (the real call only). Without the fix the
        count is 2.

        Args:
            testDatabase: Fresh in-memory database fixture.
            tmp_path: Per-test temporary directory for the JSONL log file.
        """
        refineLogFile = str(tmp_path / "refine.jsonl")
        handler = await _makeHandler(
            testDatabase,
            configManager=_makeUserMemoryConfigManager(
                enabled=True,
                jsonLogging={"enabled": True, "file": refineLogFile, "add-date-suffix": False},
            ),
        )
        _stubGetChatSettings(handler, memoryRefinementEnabled=True, refineModel="test-refine-model")
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=self._resultWithToolHistory(
                [
                    # First turn: broken pseudo-call synthesised into a marker
                    # (errorMessage set) — must NOT be counted.
                    [
                        LLMToolCall(
                            id="broken1",
                            name=ToolName.ADD_MEMORY.value,
                            parameters={},
                            errorMessage="malformed call: missing 'content' argument",
                        ),
                    ],
                    # Second turn: model retries successfully — the one real use.
                    [
                        LLMToolCall(id="ok1", name=ToolName.ADD_MEMORY.value, parameters={"content": "x"}),
                    ],
                ]
            )
        )

        chatId, userId, threadId = 490, 26, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user26", "Tina")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        entries = _readRefineLog(tmp_path / "refine.jsonl")
        assert len(entries) == 1
        entry = entries[0]
        # The synthesised broken call is excluded; only the real retry counts.
        assert entry["addCount"] == 1
        assert entry["deleteCount"] == 0
        assert entry["searchCount"] == 0

    async def test_jsonLogExcludesSynthesisedBrokenCallFromFallback(
        self, testDatabase: Database, tmp_path: Path
    ) -> None:
        """Synthesised broken-call markers in the elif fallback are not counted.

        Same regression as the history-branch test, but exercised through the
        single-turn ``elif result.toolCalls:`` branch
        (``toolUsageHistory=None``): a synthesised broken ``add_memory`` marker
        (errorMessage set) plus one real ``add_memory`` call in
        ``result.toolCalls`` must yield ``addCount == 1``, not 2.

        Args:
            testDatabase: Fresh in-memory database fixture.
            tmp_path: Per-test temporary directory for the JSONL log file.
        """
        refineLogFile = str(tmp_path / "refine.jsonl")
        handler = await _makeHandler(
            testDatabase,
            configManager=_makeUserMemoryConfigManager(
                enabled=True,
                jsonLogging={"enabled": True, "file": refineLogFile, "add-date-suffix": False},
            ),
        )
        _stubGetChatSettings(handler, memoryRefinementEnabled=True, refineModel="test-refine-model")
        handler.llmService.generateTextViaLLM = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelRunResult(
                rawResult={},
                status=ModelResultStatus.FINAL,
                resultText="",
                toolUsageHistory=None,
                toolCalls=[
                    LLMToolCall(
                        id="broken1",
                        name=ToolName.ADD_MEMORY.value,
                        parameters={},
                        errorMessage="malformed call: missing 'content' argument",
                    ),
                    LLMToolCall(id="ok1", name=ToolName.ADD_MEMORY.value, parameters={"content": "x"}),
                ],
            )
        )

        chatId, userId, threadId = 500, 27, DEFAULT_THREAD_ID
        await testDatabase.chatUsers.updateChatUser(chatId, userId, "@user27", "Mira")
        await _seedChatMessages(testDatabase, chatId=chatId, userId=userId, count=5)

        await handler._runSingleRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        entries = _readRefineLog(tmp_path / "refine.jsonl")
        assert len(entries) == 1
        entry = entries[0]
        # The synthesised broken call is excluded; only the real call counts.
        assert entry["addCount"] == 1
        assert entry["deleteCount"] == 0
        assert entry["searchCount"] == 0


# ---------------------------------------------------------------------------
# Phase 2 — user-memory LLM tools (add_memory / delete_memory / search_memories)
# ---------------------------------------------------------------------------
#
# See docs/plans/user-memories-v1.md §8.3-8.5, §14.2 for the full spec. The
# ``db.userMemories`` repository is replaced with a ``Mock`` per test (the repo
# itself has round-trip tests in ``tests/database/repositories/``), and the
# embedding model is stubbed on the shared ``LLMService`` singleton so dedup
# behaviour is deterministic without vec0 or a real embedding API.


def _stubGenerateEmbedding(
    handler: UserMemoriesHandler,
    *,
    result: Optional[Tuple[str, List[float]]] = ("test-embed-model", [0.1, 0.2, 0.3]),
) -> AsyncMock:
    """Wire ``handler.llmService.generateEmbedding`` to return a fixed result.

    The refactored tool handlers embed via ``self.llmService.generateEmbedding``
    (not the deleted ``embedAndSaveMemory`` helper). This stub mocks the method
    directly so the return value is deterministic without exercising model
    resolution, rate limiting, or a real embedding API.

    Args:
        handler: Handler under test.
        result: The ``(modelName, floats)`` tuple to return. When ``None``,
            the handler treats embedding as failed and skips dedup.

    Returns:
        The installed ``AsyncMock`` (for call assertions).
    """
    mock = AsyncMock(return_value=result)
    handler.llmService.generateEmbedding = mock  # type: ignore[method-assign]
    return mock


def _mockUserMemories(
    handler: UserMemoriesHandler,
    *,
    searchResults: Optional[List[UserMemoryDict]] = None,
) -> Mock:
    """Replace ``handler.db.userMemories`` with a ``Mock`` for tool-level isolation.

    The real ``UserMemoriesRepository`` has ``__slots__ = ()`` so individual
    methods can't be monkey-patched; the whole attribute (which IS in
    ``Database.__slots__``) is swapped out instead. Each method is an
    ``AsyncMock`` so call args can be asserted.

    Args:
        handler: Handler under test.
        searchResults: Value ``searchMemories`` returns (default ``[]``).

    Returns:
        The installed ``Mock`` (for per-method call assertions).
    """
    mockRepo = Mock()
    mockRepo.searchMemories = AsyncMock(return_value=searchResults or [])
    mockRepo.addMemory = AsyncMock()
    mockRepo.deleteMemory = AsyncMock(return_value=True)
    mockRepo.deleteMemoryEmbedding = AsyncMock(return_value=True)
    handler.db.userMemories = mockRepo  # type: ignore[method-assign]
    return mockRepo


def _stubToolChatSettings(handler: UserMemoriesHandler, *, embeddingModel: str = "test-embed-model") -> AsyncMock:
    """Stub ``handler.getChatSettings`` to return a minimal settings dict for tool tests.

    The tool handlers only read ``ChatSettingsKey.EMBEDDING_MODEL`` from the
    settings (to resolve the embedding model name). This stub returns a dict
    carrying just that key.

    Args:
        handler: Handler under test.
        embeddingModel: Value for ``EMBEDDING_MODEL``.

    Returns:
        The installed ``AsyncMock``.
    """
    settings: ChatSettingsDict = {
        ChatSettingsKey.EMBEDDING_MODEL: ChatSettingsValue(embeddingModel),
    }
    mock = AsyncMock(return_value=settings)
    handler.getChatSettings = mock  # type: ignore[method-assign]
    return mock


def _makeMemoryDict(
    *,
    memoryId: str = "mem-existing",
    content: str = "existing content",
    memoryType: str = "fact",
    score: float = 0.0,
    chatId: int = 100,
    userId: int = 7,
    threadId: int = DEFAULT_THREAD_ID,
    permanent: bool = False,
) -> UserMemoryDict:
    """Build a minimal ``UserMemoryDict`` for mocking ``searchMemories`` results.

    Args:
        memoryId: Memory id.
        content: Memory body text.
        memoryType: ``MemoryType`` string value.
        score: Cosine similarity (0.0–1.0).
        chatId: Chat id.
        userId: User id.
        threadId: Thread id.
        permanent: Permanent flag.

    Returns:
        A ``UserMemoryDict`` with the given fields.
    """
    return UserMemoryDict(
        chat_id=chatId,
        user_id=userId,
        thread_id=threadId,
        memory_id=memoryId,
        type=MemoryType(memoryType),
        content=content,
        tags=[],
        permanent=permanent,
        source=UserMemorySource.CHAT,
        embedding_model="test-embed-model",
        embedding_dimensions=3,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        updated_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        score=score,
    )


class TestLlmToolAddMemory:
    """Tests for :meth:`UserMemoriesHandler._llmToolAddMemory` (dedup state machine).

    Covers the full D5 matrix: insert / duplicate (≥0.95) / grey-zone chat-time
    (folds to duplicate) / grey-zone refinement (returns ``similar_exists``) /
    model-not-found (skip dedup, insert directly) / error path.
    """

    async def test_insertsWhenNoSimilar(self, testDatabase: Database) -> None:
        """No similar memory → ``addMemory`` called, returns ``action == "added"``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        embedMock = _stubGenerateEmbedding(handler)
        mockRepo = _mockUserMemories(handler, searchResults=[])

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolAddMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            content="user is vegan",
            type="preference",
            tags=["diet"],
            permanent=False,
        )

        assert result["done"] is True
        assert result["action"] == "added"
        assert "memory_id" in result
        mockRepo.addMemory.assert_awaited_once()
        callKwargs = mockRepo.addMemory.call_args
        assert callKwargs.kwargs["type"] == "preference"
        assert callKwargs.kwargs["content"] == "user is vegan"
        assert callKwargs.kwargs["tags"] == ["diet"]
        assert callKwargs.kwargs["permanent"] is False
        assert callKwargs.kwargs["source"] == UserMemorySource.CHAT
        embedMock.assert_awaited_once()

    async def test_duplicateWhenScoreAtOrAboveThreshold(self, testDatabase: Database) -> None:
        """Score ≥ 0.95 → ``action == "duplicate"``, no ``addMemory`` call.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        existing = _makeMemoryDict(memoryId="mem-existing", content="user is vegan", score=0.96)
        mockRepo = _mockUserMemories(handler, searchResults=[existing])

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolAddMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            content="the user follows a vegan diet",
            type="preference",
        )

        assert result["done"] is True
        assert result["action"] == "duplicate"
        assert result["existing_memory_id"] == "mem-existing"
        mockRepo.addMemory.assert_not_called()

    async def test_greyZoneFoldsToDuplicateAtChatTime(self, testDatabase: Database) -> None:
        """Score in (0.85, 0.95), no ``isRefinement`` → folds to ``duplicate``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        existing = _makeMemoryDict(score=0.90)
        mockRepo = _mockUserMemories(handler, searchResults=[existing])

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolAddMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},  # no isRefinement → chat-time
            content="something similar",
            type="fact",
        )

        assert result["done"] is True
        assert result["action"] == "duplicate"
        mockRepo.addMemory.assert_not_called()

    async def test_greyZoneReturnsSimilarExistsAtRefinement(self, testDatabase: Database) -> None:
        """Score in (0.85, 0.95), ``isRefinement=True`` → ``similar_exists`` with existing data.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        existing = _makeMemoryDict(memoryId="mem-old", content="user lives in Berlin", memoryType="fact", score=0.90)
        mockRepo = _mockUserMemories(handler, searchResults=[existing])

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolAddMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage, "isRefinement": True},
            content="the user resides in Berlin",
            type="fact",
        )

        assert result["done"] is True
        assert result["action"] == "similar_exists"
        assert result["existing_memory_id"] == "mem-old"
        assert result["existing_content"] == "user lives in Berlin"
        assert result["existing_type"] == "fact"
        assert result["score"] == 0.90
        mockRepo.addMemory.assert_not_called()

    async def test_insertsDirectlyWhenModelNotFound(self, testDatabase: Database) -> None:
        """No embedding model → skip dedup, insert directly (best-effort).

        The handler should NOT call ``searchMemories`` (no embedding to search
        with) and should still insert the memory.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler, result=None)  # embedding not available
        mockRepo = _mockUserMemories(handler)

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolAddMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            content="a new fact",
            type="fact",
        )

        assert result["done"] is True
        assert result["action"] == "added"
        mockRepo.searchMemories.assert_not_called()
        mockRepo.addMemory.assert_awaited_once()

    async def test_invalidTypeReturnsError(self, testDatabase: Database) -> None:
        """Unknown ``type`` value → ``{"done": False, "error": ...}``, no insert.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        mockRepo = _mockUserMemories(handler)

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolAddMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            content="x",
            type="not_a_valid_type",
        )

        assert result["done"] is False
        assert "error" in result
        mockRepo.addMemory.assert_not_called()

    async def test_getChatSettingsFailureReturnsErrorDict(self, testDatabase: Database) -> None:
        """``getChatSettings`` raises → handler catches, returns ``{"done": False, ...}``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        handler.getChatSettings = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        mockRepo = _mockUserMemories(handler)

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolAddMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            content="x",
            type="fact",
        )

        assert result["done"] is False
        assert "error" in result
        mockRepo.addMemory.assert_not_called()

    async def test_permanentMemoryUsesCurrentThread(self, testDatabase: Database) -> None:
        """``permanent=True`` → ``threadId`` is the current thread, not NULL (amendment #7).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        mockRepo = _mockUserMemories(handler, searchResults=[])

        ensuredMessage = _makeEnsuredMessage(threadId=42)

        result = await handler._llmToolAddMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            content="high-level bio",
            type="bio",
            permanent=True,
        )

        assert result["action"] == "added"
        callKwargs = mockRepo.addMemory.call_args
        assert callKwargs.kwargs["threadId"] == 42
        assert callKwargs.kwargs["permanent"] is True


class TestLlmToolDeleteMemory:
    """Tests for :meth:`UserMemoriesHandler._llmToolDeleteMemory` (by-id + by-query)."""

    async def test_deleteByIdDelegatesToDeleteMemory(self, testDatabase: Database) -> None:
        """``memory_id`` provided → handler delegates to ``deleteMemory`` and reports deleted.

        The handler's by-id path calls ``db.userMemories.deleteMemory`` (which
        owns its own vec0 embedding cleanup — see
        :meth:`UserMemoriesRepository.deleteMemory`, line 366, where
        ``deleteMemoryEmbedding`` cascades internally) and then invalidates the
        permanent-memories cache. The embedding cleanup is therefore a
        repository-level concern (covered by the repo tests in
        ``tests/database/repositories/test_user_memories.py``), not a separate
        handler call — asserting ``deleteMemoryEmbedding`` here would be wrong
        because this test mocks the whole repo away.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockRepo = _mockUserMemories(handler)

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolDeleteMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            memory_id="mem-123",
        )

        assert result["done"] is True
        assert result["deleted"] == 1
        assert result["memory_id"] == "mem-123"
        mockRepo.deleteMemory.assert_awaited_once_with(
            ensuredMessage.recipient.id,
            ensuredMessage.sender.id,
            "mem-123",
        )

    async def test_deleteByIdMissingReturnsDeletedFalse(self, testDatabase: Database) -> None:
        """``memory_id`` not found → ``deleted == False`` (deleteMemory returned False).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockRepo = _mockUserMemories(handler)
        mockRepo.deleteMemory = AsyncMock(return_value=False)

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolDeleteMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            memory_id="mem-gone",
        )

        assert result["done"] is True
        assert result["deleted"] == 0

    async def test_deleteByQueryRemovesOnlyMatchesAboveThreshold(self, testDatabase: Database) -> None:
        """By-query → only memories with score ≥ 0.85 are deleted.

        Seeds two search hits: score 0.90 (above threshold) and score 0.80
        (below). Only the 0.90 hit should be deleted.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        hitAbove = _makeMemoryDict(memoryId="mem-above", score=0.90)
        hitBelow = _makeMemoryDict(memoryId="mem-below", score=0.80)
        mockRepo = _mockUserMemories(handler, searchResults=[hitAbove, hitBelow])

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolDeleteMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            query="stale information",
        )

        assert result["done"] is True
        assert result["deleted"] == 1
        # Only mem-above was deleted.
        deletedIds = [call.args[2] for call in mockRepo.deleteMemory.call_args_list]
        assert "mem-above" in deletedIds
        assert "mem-below" not in deletedIds

    async def test_neitherMemoryIdNorQueryReturnsError(self, testDatabase: Database) -> None:
        """No ``memory_id`` and no ``query`` → ``{"done": False, "error": ...}``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockRepo = _mockUserMemories(handler)

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolDeleteMemory(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
        )

        assert result["done"] is False
        assert "error" in result
        mockRepo.deleteMemory.assert_not_called()


class TestLlmToolSearchMemories:
    """Tests for :meth:`UserMemoriesHandler._llmToolSearchMemories` (semantic + filter-only)."""

    async def test_semanticSearchReturnsResults(self, testDatabase: Database) -> None:
        """``query`` provided → embedding generated, results returned with count.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        results = [
            _makeMemoryDict(memoryId="m1", content="first", score=0.92),
            _makeMemoryDict(memoryId="m2", content="second", score=0.80),
        ]
        mockRepo = _mockUserMemories(handler, searchResults=results)

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolSearchMemories(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            query="what do you know",
        )

        assert result["done"] is True
        assert result["count"] == 2
        assert len(result["results"]) == 2  # type: ignore[arg-type]
        mockRepo.searchMemories.assert_awaited_once()
        # queryEmbedding should be bytes (not None) in semantic mode.
        callArgs = mockRepo.searchMemories.call_args
        assert callArgs.args[2] is not None  # queryEmbedding positional arg

    async def test_filterOnlyWhenQueryOmitted(self, testDatabase: Database) -> None:
        """No ``query`` → filter-only scan (``queryEmbedding=None``).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        results = [_makeMemoryDict(memoryId="m1", content="a preference")]
        mockRepo = _mockUserMemories(handler, searchResults=results)

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolSearchMemories(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            type="preference",
        )

        assert result["done"] is True
        assert result["count"] == 1
        callArgs = mockRepo.searchMemories.call_args
        assert callArgs.args[2] is None  # queryEmbedding is None in filter-only
        assert callArgs.kwargs["type"] == "preference"

    async def test_emptyResultsReturnCountZero(self, testDatabase: Database) -> None:
        """Search with no matches → ``count == 0``, empty results list.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        _mockUserMemories(handler, searchResults=[])

        ensuredMessage = _makeEnsuredMessage()

        result = await handler._llmToolSearchMemories(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            query="nonexistent",
        )

        assert result["done"] is True
        assert result["count"] == 0
        assert result["results"] == []

    async def test_missingEnsuredMessageReturnsError(self, testDatabase: Database) -> None:
        """No ``ensuredMessage`` in extraData → ``{"done": False, "error": ...}``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _mockUserMemories(handler)

        result = await handler._llmToolSearchMemories(  # type: ignore[attr-defined]
            extraData={},
            query="x",
        )

        assert result["done"] is False
        assert "error" in result

    # --- cross-user search (``user`` param) ---

    async def test_userOmitted_searchesOwnMemories(self, testDatabase: Database) -> None:
        """``user`` omitted → ``searchMemories`` called with the sender's id.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        mockRepo = _mockUserMemories(handler, searchResults=[])

        ensuredMessage = _makeEnsuredMessage(chatId=100, userId=7)

        await handler._llmToolSearchMemories(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
        )

        mockRepo.searchMemories.assert_awaited_once()
        # userId is the second positional arg (chatId, userId, queryEmbedding, ...)
        assert mockRepo.searchMemories.call_args.args[1] == 7

    async def test_userLoginResolvable_searchesResolvedUser(self, testDatabase: Database) -> None:
        """``user="alice"`` resolvable → ``searchMemories`` called with the resolved id (not sender's).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        mockRepo = _mockUserMemories(handler, searchResults=[])
        # Stub chatUsers so _resolveUserId finds "alice" → user_id 999.
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock(return_value={"user_id": 999})
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        ensuredMessage = _makeEnsuredMessage(chatId=100, userId=7)

        await handler._llmToolSearchMemories(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            user="alice",
        )

        mockRepo.searchMemories.assert_awaited_once()
        # Must use the RESOLVED id (999), not the sender's id (7).
        assert mockRepo.searchMemories.call_args.args[1] == 999
        mockChatUsers.getChatUserByUsername.assert_awaited_once_with(chatId=100, username="@alice")

    async def test_userLoginUnresolvable_returnsErrorAndDoesNotSearch(self, testDatabase: Database) -> None:
        """``user="ghost"`` unresolvable → error dict returned, ``searchMemories`` NOT called.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        mockRepo = _mockUserMemories(handler, searchResults=[])
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock(return_value=None)
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        ensuredMessage = _makeEnsuredMessage(chatId=100, userId=7)

        result = await handler._llmToolSearchMemories(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            user="ghost",
        )

        assert result["done"] is False
        assert "User not found: ghost" in result["error"]  # type: ignore[arg-type]
        mockRepo.searchMemories.assert_not_called()

    async def test_userNumeric_searchesByUserIdWithoutDbLookup(self, testDatabase: Database) -> None:
        """``user="12345"`` numeric → ``searchMemories`` called with 12345, no DB lookup.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        _stubToolChatSettings(handler)
        _stubGenerateEmbedding(handler)
        mockRepo = _mockUserMemories(handler, searchResults=[])
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock()
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        ensuredMessage = _makeEnsuredMessage(chatId=100, userId=7)

        await handler._llmToolSearchMemories(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            user="12345",
        )

        mockRepo.searchMemories.assert_awaited_once()
        # Must use the numeric id (12345), not the sender's id (7).
        assert mockRepo.searchMemories.call_args.args[1] == 12345
        # Numeric path must NOT touch the DB.
        mockChatUsers.getChatUserByUsername.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 5a — /memory_config wizard (user_memories browser)
# ---------------------------------------------------------------------------
#
# The wizard was repointed at the unified ``user_memories`` store. These tests
# drive the internal ``_handleUserDataConfiguration`` router (which dispatches
# to the per-action handlers) against a real in-memory database seeded via
# ``testDatabase.userMemories.addMemory(...)``. ``editMessage`` is stubbed with
# an ``AsyncMock`` so the rendered text + inline keyboard can be inspected.


def _flattenButtons(
    keyboard: Optional[Sequence[Sequence[CallbackButton]]],
) -> List[CallbackButton]:
    """Flatten a 2D inline-keyboard into a flat list of :class:`CallbackButton`.

    The wizard builds keyboards as ``List[List[CallbackButton]]`` (one row per
    button for memory entries, a shared row for prev/next nav). Flattening
    makes action-based assertions trivial regardless of row layout.

    Args:
        keyboard: The ``inlineKeyboard`` kwarg captured from ``editMessage``,
            or ``None``.

    Returns:
        Flat list of every :class:`CallbackButton` in the keyboard (empty
        when *keyboard* is ``None`` or empty).
    """
    flat: List[CallbackButton] = []
    if keyboard:
        for row in keyboard:
            for btn in row:
                flat.append(btn)
    return flat


def _buttonsForAction(
    keyboard: Optional[Sequence[Sequence[CallbackButton]]],
    action: ButtonUserDataConfigAction,
) -> List[CallbackButton]:
    """Return the buttons whose payload carries the given wizard action.

    Args:
        keyboard: The captured ``inlineKeyboard`` (or ``None``).
        action: The :class:`ButtonUserDataConfigAction` to match on.

    Returns:
        List of buttons whose ``payload[ButtonDataKey.UserDataConfigAction]``
        equals *action*.
    """
    return [btn for btn in _flattenButtons(keyboard) if btn.payload.get(ButtonDataKey.UserDataConfigAction) == action]


def _makeChatInfo(chatId: int) -> Dict[str, object]:
    """Build a minimal :class:`ChatInfoDict` for ``getChatInfo`` mocks.

    Only the fields read by ``getChatTitle`` (``chat_id`` / ``title`` /
    ``username`` / ``type``) matter for the wizard path; the rest are
    populated to satisfy the TypedDict shape.

    Args:
        chatId: Chat id to embed.

    Returns:
        A ``ChatInfoDict``-shaped dict with ``type == "private"``.
    """
    ts = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    return {
        "chat_id": chatId,
        "title": "Test Chat",
        "username": None,
        "type": ChatType.PRIVATE,
        "is_forum": False,
        "created_at": ts,
        "updated_at": ts,
    }


class TestKnowledgeConfigWizard:
    """Wizard-level tests for the repointed ``/memory_config`` browser.

    Covers the Phase 5a rewrite: the ``ChatSelected`` MemoryType picker, the
    paginated ``TopicSelected`` memory list (page-size-8 boundary), the
    per-memory ``MemorySelected`` detail view, ``DeleteMemory`` removal, the
    ``"all"`` type filter, and the ``PRIVATE``-only enforcement on the command
    decorator.
    """

    async def test_chatSelectedRendersTypePicker(self, testDatabase: Database) -> None:
        """``ChatSelected`` renders one button per ``MemoryType`` + "Все типы" + nav.

        Asserts the keyboard exposes all 5 ``MemoryType`` values plus the
        "all types" sentinel (6 ``TopicSelected`` buttons total), a back
        button (``Init``), and an exit button (``Cancel``). Each type button
        carries its ``MemoryType`` value in ``ButtonDataKey.Key`` and
        ``Page=0``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        chatId = 500
        handler.getChatInfo = AsyncMock(return_value=_makeChatInfo(chatId))  # type: ignore[method-assign]
        user = MessageSender(id=7, name="Alice", username="@alice")

        await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
            {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.ChatSelected,
                ButtonDataKey.ChatId: chatId,
            },
            messageId=MessageId(1),
            messageChatId=chatId,
            user=user,
        )

        editMock.assert_awaited_once()
        keyboard = editMock.call_args.kwargs.get("inlineKeyboard")
        # 5 MemoryType rows + "Все типы" row + back row + exit row == 8 rows.
        assert len(_flattenButtons(keyboard)) == len(list(MemoryType)) + 3

        topicButtons = _buttonsForAction(keyboard, ButtonUserDataConfigAction.TopicSelected)
        # One per MemoryType plus the "all types" sentinel.
        assert len(topicButtons) == len(list(MemoryType)) + 1
        typeValuesOnButtons = {btn.payload.get(ButtonDataKey.Key) for btn in topicButtons}
        for memType in MemoryType:
            assert memType.value in typeValuesOnButtons
        assert "all" in typeValuesOnButtons
        # Every type button starts at page 0.
        for btn in topicButtons:
            assert btn.payload.get(ButtonDataKey.Page) == 0
        # Nav buttons: back (Init) + exit (Cancel).
        assert len(_buttonsForAction(keyboard, ButtonUserDataConfigAction.Init)) == 1
        assert len(_buttonsForAction(keyboard, ButtonUserDataConfigAction.Cancel)) == 1

    async def test_topicSelectedPaginates(self, testDatabase: Database) -> None:
        """Page-size-8 boundary: 10 memories → page 0 shows 8 + Next, page 8 shows 2 + Prev.

        Seeds 10 ``FACT`` memories, then calls ``TopicSelected`` at offset 0
        and offset 8. Page 0 must render 8 ``MemorySelected`` buttons and a
        ``NextPage`` button (no ``PrevPage``); page 8 must render 2 buttons
        and a ``PrevPage`` button (no ``NextPage``). This pins the
        ``KNOWLEDGE_CONFIG_PAGE_SIZE`` boundary (fetch PAGE_SIZE+1 to detect
        the next page).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 510
        userId = 8
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Bob", username="@bob")

        for i in range(10):
            await testDatabase.userMemories.addMemory(
                chatId,
                userId,
                f"mem-{i}",
                type=MemoryType.FACT.value,
                content=f"fact number {i}",
                tags=[],
                permanent=False,
                threadId=DEFAULT_THREAD_ID,
                source=UserMemorySource.CHAT,
                embedding=None,
                embeddingModel=None,
            )

        async def renderPage(offset: int) -> Optional[Sequence[Sequence[CallbackButton]]]:
            """Drive TopicSelected at the given offset and return its keyboard.

            Args:
                offset: Page offset to pass as ``ButtonDataKey.Page``.

            Returns:
                The captured ``inlineKeyboard`` (or ``None``).
            """
            editMock.reset_mock()
            await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
                {
                    ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                    ButtonDataKey.ChatId: chatId,
                    ButtonDataKey.Key: MemoryType.FACT.value,
                    ButtonDataKey.Page: offset,
                },
                messageId=MessageId(1),
                messageChatId=chatId,
                user=user,
            )
            editMock.assert_awaited_once()
            return editMock.call_args.kwargs.get("inlineKeyboard")

        # Page 0 → 8 memory buttons + Next (no Prev).
        kb0 = await renderPage(0)
        assert len(_buttonsForAction(kb0, ButtonUserDataConfigAction.MemorySelected)) == 8
        assert len(_buttonsForAction(kb0, ButtonUserDataConfigAction.NextPage)) == 1
        assert len(_buttonsForAction(kb0, ButtonUserDataConfigAction.PrevPage)) == 0

        # Page 8 → 2 memory buttons + Prev (no Next).
        kb8 = await renderPage(8)
        assert len(_buttonsForAction(kb8, ButtonUserDataConfigAction.MemorySelected)) == 2
        assert len(_buttonsForAction(kb8, ButtonUserDataConfigAction.NextPage)) == 0
        assert len(_buttonsForAction(kb8, ButtonUserDataConfigAction.PrevPage)) == 1

    async def test_memorySelectedRendersDetailView(self, testDatabase: Database) -> None:
        """``MemorySelected`` renders content/type/tags + delete + back + exit.

        Seeds one memory with known content, type, tags, and ``permanent``,
        then asserts the rendered text contains the content, the type value,
        and the ``#tag`` token. The keyboard must offer a ``DeleteMemory``
        button, a back button (``TopicSelected``), and an exit button.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 520
        userId = 9
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Carol", username="@carol")

        memoryId = "mem-detail-1"
        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            memoryId,
            type=MemoryType.FACT.value,
            content="Lives in Berlin",
            tags=["location"],
            permanent=True,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )

        await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
            {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.MemorySelected,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: memoryId,
                ButtonDataKey.Page: 0,
            },
            messageId=MessageId(1),
            messageChatId=chatId,
            user=user,
        )

        editMock.assert_awaited_once()
        renderedText: str = editMock.call_args.kwargs.get("text", "")
        assert "Lives in Berlin" in renderedText
        assert MemoryType.FACT.value in renderedText
        assert "#location" in renderedText
        keyboard = editMock.call_args.kwargs.get("inlineKeyboard")
        assert len(_buttonsForAction(keyboard, ButtonUserDataConfigAction.DeleteMemory)) == 1
        assert len(_buttonsForAction(keyboard, ButtonUserDataConfigAction.TopicSelected)) == 1
        assert len(_buttonsForAction(keyboard, ButtonUserDataConfigAction.Cancel)) == 1

    async def test_deleteMemoryRemovesRow(self, testDatabase: Database) -> None:
        """``DeleteMemory`` removes the row and renders the "Память удалена" confirmation.

        Seeds one memory, drives ``DeleteMemory`` with its id, then asserts
        ``getMemory`` returns ``None`` afterward and the confirmation text is
        the expected Russian string.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 530
        userId = 10
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Dave", username="@dave")

        memoryId = "mem-del-1"
        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            memoryId,
            type=MemoryType.PREFERENCE.value,
            content="prefers dark mode",
            tags=[],
            permanent=False,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )
        # Sanity: the row exists before the delete.
        assert await testDatabase.userMemories.getMemory(chatId, userId, memoryId) is not None

        await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
            {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.DeleteMemory,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: memoryId,
                ButtonDataKey.Page: 0,
            },
            messageId=MessageId(1),
            messageChatId=chatId,
            user=user,
        )

        editMock.assert_awaited_once()
        assert editMock.call_args.kwargs.get("text") == "Память удалена"
        assert await testDatabase.userMemories.getMemory(chatId, userId, memoryId) is None

    @pytest.mark.parametrize(
        "failMode",
        ["returnFalse", "raiseException"],
        ids=["returnFalse", "raiseException"],
    )
    async def test_deleteMemoryFailureShowsErrorMessage(self, testDatabase: Database, failMode: str) -> None:
        """``DeleteMemory`` failure (return False OR exception) → error text, row intact.

        Regression test for the false-success bug: the OLD handler wrapped
        ``deleteMemory`` in a bare ``try/except`` that swallowed the error and
        then unconditionally rendered ``"Память удалена"`` — so on a DB
        failure (or a no-op ``False`` return, e.g. the row was already gone)
        the user was told the memory was deleted when it was not. The NEW
        handler inspects the ``bool`` return and renders a distinct error
        message on any failure path.

        Two failure modes are exercised (parametrized) since the fix touches
        both: ``returnFalse`` (``deleteMemory`` returns ``False``, no row
        matched) and ``raiseException`` (``deleteMemory`` raises, e.g. DB
        locked). In both cases the rendered text must NOT contain the success
        string ``"Память удалена"``, MUST contain the error marker
        ``"Не удалось удалить"``, and the memory row must still be present
        (the mock replaced the real delete, so the row was never removed).

        Args:
            testDatabase: Fresh in-memory database fixture.
            failMode: ``"returnFalse"`` patches ``deleteMemory`` to return
                ``False``; ``"raiseException"`` patches it to raise.
        """
        chatId = 531
        userId = 10
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Dave", username="@dave")

        memoryId = "mem-del-fail-1"
        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            memoryId,
            type=MemoryType.PREFERENCE.value,
            content="prefers dark mode",
            tags=[],
            permanent=False,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )
        # Sanity: the row exists before the (failed) delete.
        assert await testDatabase.userMemories.getMemory(chatId, userId, memoryId) is not None

        # Patch the repo method at the class level — the real
        # ``UserMemoriesRepository`` has ``__slots__ = ()`` so an instance-level
        # attribute assignment is forbidden (mirrors the established
        # ``patch.object(UserMemoriesRepository, …)`` pattern elsewhere in this
        # file). Only ``deleteMemory`` is patched; ``getMemory`` keeps the real
        # implementation so the post-call row check is meaningful.
        if failMode == "returnFalse":
            deleteMock = AsyncMock(return_value=False)
        else:
            deleteMock = AsyncMock(side_effect=RuntimeError("db locked"))
        with patch.object(UserMemoriesRepository, "deleteMemory", deleteMock):
            await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
                {
                    ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.DeleteMemory,
                    ButtonDataKey.ChatId: chatId,
                    ButtonDataKey.Key: memoryId,
                    ButtonDataKey.Page: 0,
                },
                messageId=MessageId(1),
                messageChatId=chatId,
                user=user,
            )

        editMock.assert_awaited_once()
        deleteMock.assert_awaited_once()
        renderedText: str = editMock.call_args.kwargs.get("text", "")
        # Must NOT report success.
        assert "Память удалена" not in renderedText
        # Must report the failure distinctly.
        assert "Не удалось удалить" in renderedText
        # The memory row was never actually removed (the mock replaced the real delete).
        assert await testDatabase.userMemories.getMemory(chatId, userId, memoryId) is not None

    async def test_allTypesFilterReturnsMultipleTypes(self, testDatabase: Database) -> None:
        """``Key="all"`` returns memories of every type (2 distinct → 2 buttons).

        Seeds one ``FACT`` and one ``PREFERENCE`` memory, drives
        ``TopicSelected`` with ``Key="all"`` (no type filter), and asserts
        both memories appear in the rendered list (2 ``MemorySelected``
        buttons). Pins the ``"all"`` sentinel handling in ``_renderMemoryList``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 540
        userId = 11
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Erin", username="@erin")

        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            "mem-fact-1",
            type=MemoryType.FACT.value,
            content="works as a nurse",
            tags=[],
            permanent=False,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )
        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            "mem-pref-1",
            type=MemoryType.PREFERENCE.value,
            content="vegan diet",
            tags=[],
            permanent=False,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )

        await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
            {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: "all",
                ButtonDataKey.Page: 0,
            },
            messageId=MessageId(1),
            messageChatId=chatId,
            user=user,
        )

        editMock.assert_awaited_once()
        keyboard = editMock.call_args.kwargs.get("inlineKeyboard")
        memButtons = _buttonsForAction(keyboard, ButtonUserDataConfigAction.MemorySelected)
        assert len(memButtons) == 2
        # Both memory ids appear as the button payload key.
        buttonKeys = {btn.payload.get(ButtonDataKey.Key) for btn in memButtons}
        assert "mem-fact-1" in buttonKeys
        assert "mem-pref-1" in buttonKeys

    async def test_tagFilterRendersTagsFromUserMemories(self, testDatabase: Database) -> None:
        """``TagFilter`` renders one button per distinct tag + clear + back + exit.

        Seeds memories with known tags (``work``, ``home``), drives the
        ``TagFilter`` action, and asserts the rendered keyboard exposes one
        ``TopicSelected`` button per tag carrying the tag in
        ``ButtonDataKey.Tag``. Also asserts a clear-filter button, a back
        button, and an exit button are present.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 560
        userId = 13
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Frank", username="@frank")

        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            "mem-work-1",
            type=MemoryType.FACT.value,
            content="work fact",
            tags=["work"],
            permanent=False,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )
        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            "mem-home-1",
            type=MemoryType.FACT.value,
            content="home fact",
            tags=["home"],
            permanent=False,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )

        await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
            {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TagFilter,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: MemoryType.FACT.value,
                ButtonDataKey.Page: 0,
            },
            messageId=MessageId(1),
            messageChatId=chatId,
            user=user,
        )

        editMock.assert_awaited_once()
        renderedText: str = editMock.call_args.kwargs.get("text", "")
        assert "Выберите тег" in renderedText
        keyboard = editMock.call_args.kwargs.get("inlineKeyboard")
        # Two tag buttons (TopicSelected carrying a Tag) + clear + back + exit.
        topicButtons = _buttonsForAction(keyboard, ButtonUserDataConfigAction.TopicSelected)
        tagButtons = [btn for btn in topicButtons if btn.payload.get(ButtonDataKey.Tag)]
        tagValues = {btn.payload.get(ButtonDataKey.Tag) for btn in tagButtons}
        assert tagValues == {"work", "home"}
        # The remaining TopicSelected buttons (no Tag) are: the clear-filter
        # button AND the back button (no currentTag was passed, so back has no
        # Tag either). Distinguish the clear button by its label.
        noTagButtons = [btn for btn in topicButtons if not btn.payload.get(ButtonDataKey.Tag)]
        assert len(noTagButtons) == 2
        clearTexts = [btn.text for btn in noTagButtons]
        assert any("Сбросить" in t for t in clearTexts)
        # Exit present.
        assert len(_buttonsForAction(keyboard, ButtonUserDataConfigAction.Cancel)) == 1

    async def test_topicSelectedAppliesTagFilter(self, testDatabase: Database) -> None:
        """``TopicSelected`` with a ``Tag`` narrows the list to tagged memories.

        Seeds 3 FACT memories (2 tagged ``work``, 1 tagged ``home``), drives
        ``TopicSelected`` with ``Tag="work"``, and asserts only the 2
        ``work`` memories render as ``MemorySelected`` buttons. Also asserts
        the filter/clear row and that the rendered text reflects the active
        tag.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 570
        userId = 14
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Grace", username="@grace")

        for i, tag in enumerate(["work", "work", "home"]):
            await testDatabase.userMemories.addMemory(
                chatId,
                userId,
                f"mem-{tag}-{i}",
                type=MemoryType.FACT.value,
                content=f"{tag} fact {i}",
                tags=[tag],
                permanent=False,
                threadId=DEFAULT_THREAD_ID,
                source=UserMemorySource.CHAT,
                embedding=None,
                embeddingModel=None,
            )

        await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
            {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: MemoryType.FACT.value,
                ButtonDataKey.Tag: "work",
                ButtonDataKey.Page: 0,
            },
            messageId=MessageId(1),
            messageChatId=chatId,
            user=user,
        )

        editMock.assert_awaited_once()
        renderedText: str = editMock.call_args.kwargs.get("text", "")
        assert "#work" in renderedText
        keyboard = editMock.call_args.kwargs.get("inlineKeyboard")
        memButtons = _buttonsForAction(keyboard, ButtonUserDataConfigAction.MemorySelected)
        assert len(memButtons) == 2
        buttonKeys = {btn.payload.get(ButtonDataKey.Key) for btn in memButtons}
        # The two "work" memories (ids mem-work-0 and mem-work-1).
        assert "mem-work-0" in buttonKeys
        assert "mem-work-1" in buttonKeys
        assert "mem-home-2" not in buttonKeys
        # Active-filter row shows the tag and offers a clear button.
        assert len(_buttonsForAction(keyboard, ButtonUserDataConfigAction.TagFilter)) == 1

    async def test_tagFilterClearResetsFilter(self, testDatabase: Database) -> None:
        """``TopicSelected`` with no ``Tag`` shows all memories (filter cleared).

        Seeds 3 memories with different tags, drives ``TopicSelected`` with no
        ``Tag`` key, and asserts all 3 render (no tag filtering). Verifies the
        unfiltered path and that the "filter by tag" entry button (not the
        active-filter variant) is shown.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 580
        userId = 15
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Heidi", username="@heidi")

        for i, tag in enumerate(["work", "home", "hobby"]):
            await testDatabase.userMemories.addMemory(
                chatId,
                userId,
                f"mem-clear-{i}",
                type=MemoryType.FACT.value,
                content=f"{tag} fact {i}",
                tags=[tag],
                permanent=False,
                threadId=DEFAULT_THREAD_ID,
                source=UserMemorySource.CHAT,
                embedding=None,
                embeddingModel=None,
            )

        await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
            {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: MemoryType.FACT.value,
                ButtonDataKey.Page: 0,
            },
            messageId=MessageId(1),
            messageChatId=chatId,
            user=user,
        )

        editMock.assert_awaited_once()
        renderedText: str = editMock.call_args.kwargs.get("text", "")
        # No "#tag" in the title (filter is off).
        assert "#" not in renderedText
        keyboard = editMock.call_args.kwargs.get("inlineKeyboard")
        memButtons = _buttonsForAction(keyboard, ButtonUserDataConfigAction.MemorySelected)
        assert len(memButtons) == 3
        # The unfiltered list shows the "filter by tag" entry button (TagFilter),
        # NOT the active-filter/clear variant.
        tagFilterButtons = _buttonsForAction(keyboard, ButtonUserDataConfigAction.TagFilter)
        assert len(tagFilterButtons) == 1

    async def test_tagFilterPersistsAcrossPagination(self, testDatabase: Database) -> None:
        """Next/Prev buttons carry the active tag so the filter survives paging.

        Seeds 10 FACT memories all tagged ``work`` (exceeds
        ``KNOWLEDGE_CONFIG_PAGE_SIZE`` = 8), drives ``TopicSelected`` with
        ``Tag="work"`` at offset 0, and asserts the ``NextPage`` button
        payload carries ``Tag="work"``. Then simulates the next page and
        asserts results are still tag-filtered.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 590
        userId = 16
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Ivan", username="@ivan")

        for i in range(10):
            await testDatabase.userMemories.addMemory(
                chatId,
                userId,
                f"mem-page-{i}",
                type=MemoryType.FACT.value,
                content=f"work fact {i}",
                tags=["work"],
                permanent=False,
                threadId=DEFAULT_THREAD_ID,
                source=UserMemorySource.CHAT,
                embedding=None,
                embeddingModel=None,
            )

        await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
            {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: MemoryType.FACT.value,
                ButtonDataKey.Tag: "work",
                ButtonDataKey.Page: 0,
            },
            messageId=MessageId(1),
            messageChatId=chatId,
            user=user,
        )

        editMock.assert_awaited_once()
        keyboard = editMock.call_args.kwargs.get("inlineKeyboard")
        # Page 0 → 8 memory buttons + Next (no Prev).
        assert len(_buttonsForAction(keyboard, ButtonUserDataConfigAction.MemorySelected)) == 8
        nextButtons = _buttonsForAction(keyboard, ButtonUserDataConfigAction.NextPage)
        assert len(nextButtons) == 1
        # The tag MUST ride on the NextPage payload.
        assert nextButtons[0].payload.get(ButtonDataKey.Tag) == "work"

    def test_memoryConfigPrivateOnly(self) -> None:
        """``memory_config_command`` is ``PRIVATE``-only (not ``GROUP``).

        Inspects the ``@commandHandlerV2`` metadata attached to the unbound
        command function and asserts ``CommandPermission.PRIVATE`` is in
        ``availableFor`` while ``CommandPermission.GROUP`` is not — the wizard
        is intentionally private-chats only.

        Args:
            testDatabase: (unused) — kept off the signature; this is a pure
                metadata assertion.
        """
        info = getattr(UserMemoriesHandler.memory_config_command, "_commandHandlerInfoV2")
        assert CommandPermission.PRIVATE in info.availableFor
        assert CommandPermission.GROUP not in info.availableFor

    def test_memoryConfigCommandRenamed(self) -> None:
        """The command decorator registers ``memory_config`` (not knowledge_config).

        Pins the Task 1 rename: the ``@commandHandlerV2`` metadata must carry
        ``"memory_config"`` in ``commands`` and must NOT carry the old
        ``"knowledge_config"`` alias (no backward-compat alias is kept).

        Args:
            testDatabase: (unused) — kept off the signature; this is a pure
                metadata assertion.
        """
        info = getattr(UserMemoriesHandler.memory_config_command, "_commandHandlerInfoV2")
        assert "memory_config" in info.commands
        assert "knowledge_config" not in info.commands

    async def test_addMemoryButtonShownInList(self, testDatabase: Database) -> None:
        """``TopicSelected`` for a specific type renders the "Добавить память" button.

        Seeds one ``FACT`` memory, drives ``TopicSelected`` with
        ``Key=MemoryType.FACT.value``, and asserts exactly one ``AddMemory``
        button is rendered carrying the type in ``ButtonDataKey.Key``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 600
        userId = 17
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Karl", username="@karl")

        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            "mem-am-1",
            type=MemoryType.FACT.value,
            content="a fact",
            tags=[],
            permanent=False,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )

        await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
            {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: MemoryType.FACT.value,
                ButtonDataKey.Page: 0,
            },
            messageId=MessageId(1),
            messageChatId=chatId,
            user=user,
        )

        editMock.assert_awaited_once()
        keyboard = editMock.call_args.kwargs.get("inlineKeyboard")
        addButtons = _buttonsForAction(keyboard, ButtonUserDataConfigAction.AddMemory)
        assert len(addButtons) == 1
        assert "Добавить память" in addButtons[0].text
        assert addButtons[0].payload.get(ButtonDataKey.Key) == MemoryType.FACT.value

    async def test_addMemoryButtonNotShownForAllTypes(self, testDatabase: Database) -> None:
        """``TopicSelected`` with ``Key="all"`` does NOT render the add button.

        The "Add memory" button is intentionally hidden for the "all types"
        view so the new memory always inherits a concrete ``MemoryType``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 610
        userId = 18
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Lena", username="@lena")

        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            "mem-am-2",
            type=MemoryType.FACT.value,
            content="a fact",
            tags=[],
            permanent=False,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )

        await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
            {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.TopicSelected,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: "all",
                ButtonDataKey.Page: 0,
            },
            messageId=MessageId(1),
            messageChatId=chatId,
            user=user,
        )

        editMock.assert_awaited_once()
        keyboard = editMock.call_args.kwargs.get("inlineKeyboard")
        addButtons = _buttonsForAction(keyboard, ButtonUserDataConfigAction.AddMemory)
        assert len(addButtons) == 0

    async def test_addMemoryCreatesMemory(self, testDatabase: Database) -> None:
        """Full free-text flow: seed state → send message → memory created.

        Seeds the ``UserDataConfig`` state (as ``_handleConfigAction_AddMemory``
        would), sends a free-text message via ``newMessageHandler``, and asserts
        the handler returns ``FINAL`` and the memory is persisted with the typed
        content and the selected type. This exercises the restored free-text
        path end-to-end.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 620
        userId = 19
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        _stubGetChatSettings(handler, memoryRefinementEnabled=False)

        handler.cache.setUserState(
            userId=userId,
            stateKey=UserActiveActionEnum.UserDataConfig,
            value={
                "data": {
                    ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.SetMemoryContent,
                    ButtonDataKey.ChatId: chatId,
                    ButtonDataKey.Key: MemoryType.PREFERENCE.value,
                },
                "messageId": MessageId(1),
                "messageChatId": chatId,
            },
        )

        ensuredMessage = _makeEnsuredMessage(chatId=chatId, userId=userId, messageText="prefers dark mode")
        result = await handler.newMessageHandler(ensuredMessage, Mock())  # type: ignore[attr-defined]
        assert result == HandlerResultStatus.FINAL

        memories = await testDatabase.userMemories.searchMemories(
            chatId,
            userId,
            None,
            type=MemoryType.PREFERENCE.value,
            threadId=None,
            limit=10,
            embeddingModel=None,
        )
        assert len(memories) == 1
        assert memories[0]["content"] == "prefers dark mode"

    async def test_addMemoryEmptyContentShowsError(self, testDatabase: Database) -> None:
        """Empty/whitespace content → error message rendered, no memory created.

        Drives ``SetMemoryContent`` directly with a whitespace-only ``Value``.
        Asserts the rendered text marks the error and that no memory row was
        inserted.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 630
        userId = 20
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        user = MessageSender(id=userId, name="Nina", username="@nina")

        await handler._handleUserDataConfiguration(  # type: ignore[attr-defined]
            {
                ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.SetMemoryContent,
                ButtonDataKey.ChatId: chatId,
                ButtonDataKey.Key: MemoryType.FACT.value,
                ButtonDataKey.Value: "   ",
            },
            messageId=MessageId(1),
            messageChatId=chatId,
            user=user,
        )

        editMock.assert_awaited_once()
        renderedText: str = editMock.call_args.kwargs.get("text", "")
        assert "пустым" in renderedText
        memories = await testDatabase.userMemories.searchMemories(
            chatId,
            userId,
            None,
            threadId=None,
            limit=10,
            embeddingModel=None,
        )
        assert len(memories) == 0

    async def test_addMemoryIsEphemeralAndUserSource(self, testDatabase: Database) -> None:
        """Created memory is ephemeral, ``source=USER``, no embedding.

        Full free-text flow (seed state → send message), then asserts the
        persisted memory has ``permanent is False``, ``source ==
        UserMemorySource.USER``, and ``embedding_model is None``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 640
        userId = 21
        handler = await _makeHandler(testDatabase)
        editMock = AsyncMock()
        handler.editMessage = editMock  # type: ignore[method-assign]
        _stubGetChatSettings(handler, memoryRefinementEnabled=False)

        handler.cache.setUserState(
            userId=userId,
            stateKey=UserActiveActionEnum.UserDataConfig,
            value={
                "data": {
                    ButtonDataKey.UserDataConfigAction: ButtonUserDataConfigAction.SetMemoryContent,
                    ButtonDataKey.ChatId: chatId,
                    ButtonDataKey.Key: MemoryType.FACT.value,
                },
                "messageId": MessageId(1),
                "messageChatId": chatId,
            },
        )

        ensuredMessage = _makeEnsuredMessage(chatId=chatId, userId=userId, messageText="lives in Paris")
        await handler.newMessageHandler(ensuredMessage, Mock())  # type: ignore[attr-defined]

        memories = await testDatabase.userMemories.searchMemories(
            chatId,
            userId,
            None,
            type=MemoryType.FACT.value,
            threadId=None,
            limit=10,
            embeddingModel=None,
        )
        assert len(memories) == 1
        mem = memories[0]
        assert mem["permanent"] is False
        assert mem["source"] == UserMemorySource.USER
        assert mem["embedding_model"] is None


class TestGetMyDataCommand:
    """Tests for the repointed ``/get_my_data`` command (now reads ``user_memories``).

    Phase 5a repointed the dump at ``db.userMemories``; the legacy
    ``user_data`` key-value path is retired. This verifies a seeded memory's
    content reaches the sent message.
    """

    async def test_getMyDataDumpsUserMemories(self, testDatabase: Database) -> None:
        """``/get_my_data`` renders the caller's memories in a code block.

        Seeds one memory for ``(chatId, userId)``, drives
        ``get_my_data_command`` with ``sendMessage`` stubbed, and asserts the
        sent message text contains the ``[type] content`` line produced by
        ``_formatMemoryLine``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        chatId = 550
        userId = 12
        handler = await _makeHandler(testDatabase)
        sendMock = AsyncMock()
        handler.sendMessage = sendMock  # type: ignore[method-assign]

        await testDatabase.userMemories.addMemory(
            chatId,
            userId,
            "mem-dump-1",
            type=MemoryType.FACT.value,
            content="GET_MY_DATA_MARKER",
            tags=["timezone"],
            permanent=False,
            threadId=DEFAULT_THREAD_ID,
            source=UserMemorySource.CHAT,
            embedding=None,
            embeddingModel=None,
        )

        ensuredMessage = _makeEnsuredMessage(chatId=chatId, userId=userId)
        await handler.get_my_data_command(ensuredMessage, "get_my_data", "", Mock(), None)  # type: ignore[attr-defined]

        sendMock.assert_awaited_once()
        sentText: str = sendMock.call_args.kwargs.get("messageText", "")
        assert "GET_MY_DATA_MARKER" in sentText
        assert MemoryType.FACT.value in sentText
        assert "#timezone" in sentText
