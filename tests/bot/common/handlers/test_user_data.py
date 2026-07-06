"""Tests for :class:`UserDataHandler` (memory-refinement phases 7a + 7b).

Phase 7a — deterministic behaviours that hold without any LLM interaction:

* ``(A)`` ``_llmToolDeleteUserData`` removes a single scoped key from user data
  and leaves sibling keys untouched.
* ``(B)`` ``newMessageHandler`` increments the per-``(chatId, userId, threadId)``
  ``_accounting`` counter and returns ``NEXT`` when
  ``ChatSettingsKey.MEMORY_REFINEMENT_ENABLED`` is on.
* ``(C)`` ``newMessageHandler`` leaves ``_accounting`` untouched when the feature
  is disabled.

Phase 7b — the CRON refinement loop (``_dtCronJob`` / ``_runRefinement``) with
``LLMService.generateTextViaLLM`` mocked per-handler-instance:

* ``(F)`` ``_dtCronJob`` early-returns when ``[user-memory].enabled`` is false.
* ``(G)`` ``_dtCronJob`` early-returns when ``_refineLock`` is already held.
* ``(H)`` ``_dtCronJob`` dispatches refinement for a due (count-threshold) entry,
  resets its counter, and persists the summary + cursors.
* ``(I)`` ``_runRefinement`` bails when fewer than ``min-messages`` are available.
* ``(J)`` ``_dtCronJob`` dispatches a never-refined (TS=0) user due-by-time even
  when its new-message counter is below ``min-messages``; ``_runRefinement``
  then pulls lifetime history, bails on too few messages, and advances the
  in-memory ``_lastRefinedTS`` so the user is not retried every tick.
* ``(K)`` ``_dtCronJob`` uses the credit-consumed counter reset: increments that
  arrive during the (slow) LLM call are preserved, not zeroed (follow-up #1).

The handler is constructed against a real in-memory database (``testDatabase``
fixture) and the real :class:`CacheService` singleton (reset per test by the
local autouse fixture), so the ``setChatUserData`` / ``unsetChatUserData`` /
``getChatUserData`` round-trip in test (A) hits a genuine SQLite backend.
``getChatSettings`` is stubbed at the instance level for tests (B)/(C) to flip
the boolean ``MEMORY_REFINEMENT_ENABLED`` flag, mirroring the pattern used by
the other handler tests under ``tests/bot/common/handlers/``.
"""

import datetime
import json
import time
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import AsyncMock, Mock

import pytest

from internal.bot.common.handlers.base import HandlerResultStatus
from internal.bot.common.handlers.user_data import UserDataHandler
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
from internal.database import Database
from internal.database.utils import DEFAULT_THREAD_ID
from internal.models import MessageId
from internal.services.cache import CacheService
from internal.services.queue_service.service import QueueService
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction
from lib.ai import ModelResultStatus, ModelRunResult

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

    ``BaseBotHandler.__init__`` reads ``getBotConfig()``; ``UserDataHandler.__init__``
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


async def _makeHandler(testDatabase: Database, configManager: Optional[Mock] = None) -> UserDataHandler:
    """Construct a :class:`UserDataHandler` wired to a real in-memory database.

    Resets the ``CacheService`` singleton, injects *testDatabase* into it (so
    ``handler.cache.setChatUserData`` / ``getChatUserData`` round-trip through
    SQLite), then builds the handler. The handler's
    ``BaseBotHandler.__init__`` re-fetches the same cache singleton, so
    ``handler.cache`` is the injected instance.

    Args:
        testDatabase: Fresh in-memory :class:`Database` (``testDatabase``
            fixture).
        configManager: Optional ``ConfigManager`` stub. When omitted, the
            default :func:`_makeConfigManager` is used (no ``user-memory``
            section). Pass :func:`_makeUserMemoryConfigManager` to drive the
            memory-refinement CRON path.

    Returns:
        A fully constructed :class:`UserDataHandler` whose ``cache`` is backed
        by *testDatabase*.
    """
    CacheService._instance = None
    cache = CacheService.getInstance()
    await cache.injectDatabase(testDatabase)

    handler = UserDataHandler(
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

    The ``_llmToolDeleteUserData`` guard asserts
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
    ``newMessageHandler`` and ``_runRefinement``) plus the two prompt settings
    (``MEMORY_REFINE_SYSTEM_PROMPT`` / ``MEMORY_REFINE_USER_PROMPT_TEMPLATE``)
    now read by ``_runRefinement``. The user-prompt template MUST contain the
    three ``.format()`` placeholders so the template render doesn't raise.

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
        Mapping with the refinement toggle + prompt keys (+ optional model(s)).
    """
    settings: ChatSettingsDict = {
        ChatSettingsKey.MEMORY_REFINEMENT_ENABLED: ChatSettingsValue("true" if memoryRefinementEnabled else "false"),
        ChatSettingsKey.MEMORY_REFINE_SYSTEM_PROMPT: ChatSettingsValue("system prompt placeholder"),
        ChatSettingsKey.MEMORY_REFINE_USER_PROMPT_TEMPLATE: ChatSettingsValue(
            "{existingUserData}\n{existingSummary}\n{messages}"
        ),
    }
    if refineModel is not None:
        settings[ChatSettingsKey.MEMORY_REFINE_MODEL] = ChatSettingsValue(refineModel)
    if refineFallbackModel is not None:
        settings[ChatSettingsKey.MEMORY_REFINE_FALLBACK_MODEL] = ChatSettingsValue(refineFallbackModel)
    return settings


def _stubGetChatSettings(
    handler: UserDataHandler,
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
# (A) _llmToolDeleteUserData
# ---------------------------------------------------------------------------


class TestLlmToolDeleteUserData:
    """Tests for :meth:`UserDataHandler._llmToolDeleteUserData`."""

    async def test_deleteUserDataRemovesOnlyTargetKey(self, testDatabase: Database) -> None:
        """``_llmToolDeleteUserData`` removes the named key and leaves siblings intact.

        Two keys are pre-populated (``hobby`` and ``name``); after deleting
        ``hobby`` the ``getChatUserData`` round-trip must contain only ``name``,
        and the tool's return dict must be ``{"done": True, "key": ...}``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        chatId = 100
        userId = 7

        await handler.cache.setChatUserData(chatId=chatId, userId=userId, key="hobby", value="chess")
        await handler.cache.setChatUserData(chatId=chatId, userId=userId, key="name", value="alice")

        ensuredMessage = _makeEnsuredMessage(chatId=chatId, userId=userId)

        result = await handler._llmToolDeleteUserData(  # type: ignore[attr-defined]
            extraData={"ensuredMessage": ensuredMessage},
            key="hobby",
        )

        assert result == {"done": True, "key": "hobby"}

        userData = await handler.cache.getChatUserData(chatId=chatId, userId=userId)
        assert "hobby" not in userData
        assert userData.get("name") == "alice"


# ---------------------------------------------------------------------------
# (B) + (C) newMessageHandler accounting
# ---------------------------------------------------------------------------


class TestNewMessageHandlerAccounting:
    """Tests for the ``_accounting`` increment in :meth:`UserDataHandler.newMessageHandler`.

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
# (F-J) _dtCronJob / _runRefinement
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
        0, and ``chat_users.metadata.memoryRefinement["0"]`` carries the mocked
        summary plus a fresh ``lastProcessedMessageDate``. The
        ``lastRefinedTS`` is NO LONGER persisted to the DB entry — it is tracked
        in-memory on ``handler._lastRefinedTS`` instead.

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
        assert entry.get("summary") == "Refined summary text"
        # lastRefinedTS is NO LONGER persisted to the DB entry (moved in-memory).
        assert "lastRefinedTS" not in entry
        # Instead it is tracked in handler._lastRefinedTS.
        lastRefined = handler._lastRefinedTS.get((chatId, userId, threadId))  # type: ignore[attr-defined]
        assert isinstance(lastRefined, int)
        assert abs(int(time.time()) - lastRefined) < 10
        # _runRefinement persists the refinement cursor from the NEWEST message
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

    async def test_runRefinementBailsWhenFewerThanMinMessages(self, testDatabase: Database) -> None:
        """Below ``min-messages`` → ``_runRefinement`` returns with no LLM call.

        Creates a chat_users row + only 2 messages (below the 5-message floor),
        then calls ``_runRefinement`` directly. The LLM mock must not fire and
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

        await handler._runRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        mockGenerate.assert_not_called()
        userInfo = await testDatabase.chatUsers.getChatUser(chatId=chatId, userId=userId)
        metadata = handler.parseUserMetadata(userInfo)
        assert metadata.get("memoryRefinement", {}).get(str(threadId)) is None

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
        enters the due list. ``_runRefinement`` then fetches the lifetime
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
        # Fewer than min-messages (5) LIFETIME messages → _runRefinement bails.
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
    ``_runRefinement`` after the LLM call succeeds and before the empty-summary
    early-return, so both populated and empty summaries are logged.

    Each test drives a real ``_runRefinement`` against the in-memory database
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

        await handler._runRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

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

        await handler._runRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        # No dated-suffix variant either — glob covers refine.jsonl and refine.jsonl.YYYY-MM-DD.
        assert list(tmp_path.glob("refine.jsonl*")) == []

    async def test_refinementJsonLogWritesAllFields(self, testDatabase: Database, tmp_path: Path) -> None:
        """Successful refinement → exactly one JSONL line with all 11 fields.

        Seeds 5 messages (ids 1000..1004, newest=1004), runs ``_runRefinement``
        with a mocked non-fallback result, and asserts the written JSONL line
        carries every field with the expected value, including the resolved
        primary model id and the LLM elapsed time.

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

        await handler._runRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

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
        # ``date`` is present and ISO-parseable.
        datetime.datetime.fromisoformat(entry["date"])

    async def test_refinementJsonLogWritesEmptySummary(self, testDatabase: Database, tmp_path: Path) -> None:
        """Empty summary → JSONL line is still written with ``summary == ""``.

        The hook is placed before the empty-summary early-return, so an empty
        result must still be logged. Mocks ``generateTextViaLLM`` to return
        ``resultText=""`` and asserts the entry exists with an empty summary
        and that no memory entry is persisted (the early-return path).

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

        await handler._runRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

        entries = _readRefineLog(tmp_path / "refine.jsonl")
        assert len(entries) == 1
        assert entries[0]["summary"] == ""
        assert entries[0]["chatId"] == chatId
        assert entries[0]["userId"] == userId
        # Empty summary → early-return path → no memory entry persisted.
        userInfo = await testDatabase.chatUsers.getChatUser(chatId=chatId, userId=userId)
        metadata = handler.parseUserMetadata(userInfo)
        assert metadata.get("memoryRefinement", {}).get(str(threadId)) is None

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

        await handler._runRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

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

        await handler._runRefinement(chatId, userId, threadId)  # type: ignore[attr-defined]

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
