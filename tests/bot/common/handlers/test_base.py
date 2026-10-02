"""Tests for the ``cache.chatUserMetadataLock()`` contract of :meth:`BaseBotHandler.setUserMetadata`.

Covers behaviour area (F): the ``isUpdate=True`` read-merge-write path must acquire
``cache.chatUserMetadataLock()`` exactly once around its read-merge-write, while the
full-replace path must not. Removing that wrapper reintroduces a lost-update race, and
these tests fail if the wrapper is dropped.

:meth:`BaseBotHandler.setUserMetadata` lives on :class:`BaseBotHandler`, which is
abstract / mixin-bound and not instantiated directly. It is exercised here through its
concrete subclass :class:`UserMemoriesHandler`, constructed against a real in-memory database
(``testDatabase`` fixture) with the ``CacheService`` singleton reset per test by the local
autouse fixture. For the ``isUpdate=True`` path the handler reads via
``cache.getUserMetadata``; the autouse singleton reset plus
``cache.injectDatabase(testDatabase)`` in ``_makeHandler`` bind the handler's ``self.cache``
to a fresh :class:`CacheService`, and the cache is then swapped for a mock per-test so the
lock acquisition can be spied on.
"""

import asyncio
import datetime
import logging
import types
from typing import Dict, Generator, List, Optional, TypedDict, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest

from internal.bot.common.handlers.user_memories import UserMemoriesHandler, _formatMemoriesBlockRaw
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
    ChatType,
    EnsuredMessage,
    MessageRecipient,
    MessageSender,
    MessageType,
    UserMetadataDict,
)
from internal.database import Database
from internal.database.models import MediaStatus, MemoryType, MessageCategory, UserMemorySource
from internal.database.repositories.chat_messages import ChatMessageDict
from internal.database.repositories.user_memories import UserMemoryDict
from internal.models import MessageId
from internal.services.cache import CacheService
from internal.services.llm.service import LLMService
from internal.services.queue_service import QueueService
from internal.services.storage import StorageService
from internal.services.stt import STTOutcome, STTService
from lib.ai import ModelMessage, ModelResultStatus, ModelRunResult
from lib.ai.manager import LLMManager
from lib.stt.models import STTErrorCode

# ---------------------------------------------------------------------------
# Singleton hygiene
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _resetCacheServiceSingleton() -> Generator[None, None, None]:
    """Reset the ``CacheService`` and ``QueueService`` singletons around every test.

    Keeps the closed in-memory database from one test from leaking into the
    next via the ``CacheService`` singleton (which is not reset by
    ``tests/conftest.py``). The ``QueueService`` singleton additionally
    accumulates CRON_JOB handler registrations from every ``_makeHandler``
    call (each constructed ``UserMemoriesHandler`` registers its
    ``_dtCronJob`` on the process-wide singleton), and resetting
    ``LLMService`` does not remove them — so without a reset those
    references persist across the session. Resetting both before *and*
    after each test keeps every test hermetic and prevents leakage into
    other test modules that run afterwards (same pattern as
    ``tests/bot/common/handlers/test_user_memories.py``).

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

    ``UserMemoriesHandler.__init__`` reads ``get("user-memory", {})`` to cache the
    refinement config; returning ``{}`` leaves the feature disabled and makes
    thresholds fall back to module constants. These tests only exercise the
    inherited ``setUserMetadata`` helper, so the cached values are unused.

    Returns:
        ``Mock`` exposing ``getBotConfig()`` returning a token/owners dict and
        ``get(key, default)`` returning ``{}`` for any key.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test_token", "owners": [123456]})
    cm.get = Mock(return_value={})
    return cm


async def _makeHandler(testDatabase: Database) -> UserMemoriesHandler:
    """Construct a :class:`UserMemoriesHandler` wired to a real in-memory database.

    Args:
        testDatabase: Fresh in-memory :class:`Database`` (``testDatabase``
            fixture).

    Returns:
        A :class:`UserMemoriesHandler` whose ``db`` is *testDatabase*, used as the
        host for the inherited ``setUserMetadata`` helper.
    """
    CacheService._instance = None
    cache = CacheService.getInstance()
    await cache.injectDatabase(testDatabase)

    handler = UserMemoriesHandler(
        configManager=_makeConfigManager(),
        database=testDatabase,
        botProvider=BotProvider.TELEGRAM,
    )
    return handler


class _CountingMetadataLock:
    """Async CM stand-in that counts acquisitions for lock-usage assertions.

    Stands in for the context manager returned by
    :meth:`CacheService.chatUserMetadataLock` so a test can assert that a given
    code path acquired the lock. Every ``__aenter__`` increments
    :attr:`enterCount`; ``__aexit__`` is a no-op that does not suppress
    exceptions. Used to pin down that ``setUserMetadata(isUpdate=True)``
    serializes its read-merge-write inside the lock.
    """

    def __init__(self) -> None:
        self.enterCount: int = 0
        """Number of times the context was entered (incremented on ``__aenter__``)."""

    async def __aenter__(self) -> None:
        """Enter the context: increment :attr:`enterCount`.

        Returns:
            None.
        """
        self.enterCount += 1

    async def __aexit__(
        self,
        excType: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[types.TracebackType],
    ) -> bool:
        """Exit the context.

        Does not suppress exceptions (always returns ``False``).

        Args:
            excType: Exception type raised inside the ``async with`` body, or
                ``None`` when no exception occurred.
            exc: Exception instance, or ``None``.
            tb: Traceback object, or ``None``.

        Returns:
            ``False`` so any raised exception propagates unchanged.
        """
        return False


# ---------------------------------------------------------------------------
# (F) setUserMetadata lock contract
# ---------------------------------------------------------------------------


class TestSetUserMetadataLockContract:
    """Tests pinning the ``cache.chatUserMetadataLock()`` acquisition in ``setUserMetadata``.

    ``BaseBotHandler.setUserMetadata(isUpdate=True)`` performs a read-merge-write
    that must be serialized against concurrent metadata writers; the
    serialization is provided by ``cache.chatUserMetadataLock()``. Removing that
    wrapper reintroduces a lost-update race, and these tests fail if the wrapper
    is dropped, pinning the contract down.
    """

    async def test_setUserMetadata_isUpdate_acquiresMetadataLock(self, testDatabase: Database) -> None:
        """``isUpdate=True`` acquires ``chatUserMetadataLock`` exactly once.

        Builds a handler, swaps its cache for a mock whose
        ``chatUserMetadataLock`` returns a :class:`_CountingMetadataLock`, then
        calls ``setUserMetadata(..., isUpdate=True)``. The lock must be entered
        exactly once, and the recorded ``updateUserMetadata`` payload must be
        the shallow merge of the existing dict with the new one (proving the
        read-merge-write happened inside the lock).

        Args:
            testDatabase: Fresh in-memory database fixture (used to build the
                handler; the cache is swapped for a mock afterwards).
        """
        handler = await _makeHandler(testDatabase)

        countingLock = _CountingMetadataLock()
        mockCache = Mock()
        mockCache.chatUserMetadataLock = Mock(return_value=countingLock)
        mockCache.getUserMetadata = AsyncMock(return_value=cast(UserMetadataDict, {"existingKey": "existingVal"}))
        mockCache.updateUserMetadata = AsyncMock(return_value=None)
        handler.cache = mockCache  # type: ignore[assignment]

        await handler.setUserMetadata(
            chatId=100,
            userId=7,
            metadata=cast(UserMetadataDict, {"newKey": "newVal"}),
            isUpdate=True,
        )

        assert countingLock.enterCount == 1
        mockCache.updateUserMetadata.assert_awaited_once_with(
            chatId=100,
            userId=7,
            metadata={"existingKey": "existingVal", "newKey": "newVal"},
        )

    async def test_setUserMetadata_fullReplace_alsoAcquiresMetadataLock(self, testDatabase: Database) -> None:
        """``isUpdate=False`` also acquires ``chatUserMetadataLock`` exactly once.

        The full-replace path writes ``metadata`` verbatim with no prior read,
        but it still runs inside ``chatUserMetadataLock()`` so it cannot be
        clobbered by a concurrent read-merge-write from another handler. Pins
        the contract that BOTH ``isUpdate`` paths are serialized.

        Args:
            testDatabase: Fresh in-memory database fixture (used to build the
                handler; the cache is swapped for a mock afterwards).
        """
        handler = await _makeHandler(testDatabase)

        countingLock = _CountingMetadataLock()
        mockCache = Mock()
        mockCache.chatUserMetadataLock = Mock(return_value=countingLock)
        mockCache.getUserMetadata = AsyncMock(return_value=cast(UserMetadataDict, {}))
        mockCache.updateUserMetadata = AsyncMock(return_value=None)
        handler.cache = mockCache  # type: ignore[assignment]

        await handler.setUserMetadata(
            chatId=100,
            userId=7,
            metadata=cast(UserMetadataDict, {"newKey": "newVal"}),
            isUpdate=False,
        )

        assert countingLock.enterCount == 1
        mockCache.getUserMetadata.assert_not_called()
        mockCache.updateUserMetadata.assert_awaited_once_with(chatId=100, userId=7, metadata={"newKey": "newVal"})


# ---------------------------------------------------------------------------
# User-memories formatting contract — _formatMemoriesBlockRaw
# ---------------------------------------------------------------------------
#
# The Phase-3a ``_buildMemoriesBlock`` / ``_injectMemoriesBlock`` methods were
# removed from ``BaseBotHandler`` when memory injection moved to
# ``MessagePreprocessorHandler.injectMemories``. The rendering logic survives
# as the module function ``_formatMemoriesBlockRaw`` in ``user_memories.py``; these
# tests pin the render contract (header omission, tag formatting, sort order)
# against that function.
#
# Coverage for ``MessagePreprocessorHandler.injectMemories`` lives in
# ``tests/bot/common/handlers/test_message_preprocessor.py``:
# ``TestInjectMemoriesCompactFormat`` covers the compact-format write path,
# and ``TestNewMessageHandlerDispatchGates`` covers dispatch gating.


_CHAT_ID = 200
_USER_ID = 7
_THREAD_ID = 0
_TS = datetime.datetime(2026, 7, 7, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _memoryDict(
    *,
    content: str,
    memType: str,
    tags: Optional[List[str]] = None,
    permanent: bool = False,
    threadId: Optional[int] = _THREAD_ID,
    updated_at: datetime.datetime = _TS,
) -> UserMemoryDict:
    """Build a minimal :class:`UserMemoryDict` for injection-block tests.

    Args:
        content: Memory body text.
        memType: ``MemoryType`` string value (bio/preference/fact/event/relationship).
        tags: Tag list (defaults to empty).
        permanent: Permanent flag.
        threadId: Thread scope (``None`` for cross-thread permanent).
        updated_at: Last-update timestamp.

    Returns:
        A :class:`UserMemoryDict` with the fields the formatter reads populated.
    """
    return cast(
        UserMemoryDict,
        {
            "chat_id": _CHAT_ID,
            "user_id": _USER_ID,
            "thread_id": threadId,
            "memory_id": f"mid-{content[:8]}",
            "type": MemoryType(memType),
            "content": content,
            "tags": tags or [],
            "permanent": permanent,
            "source": UserMemorySource.REFINEMENT,
            "model_id": None,
            "created_at": _TS,
            "updated_at": updated_at,
        },
    )


class TestFormatMemoriesBlockRaw:
    """Direct tests on :func:`_formatMemoriesBlockRaw` (module function).

    Locks the render contract independently of the DB / settings: header
    omission for empty sections, tag formatting, and permanent-section sort
    order (by ``type`` then ``updated_at``). These tests were originally aimed
    at the ``BaseBotHandler._formatMemoriesBlock`` staticmethod; the rendering
    logic now lives as the module-level ``_formatMemoriesBlockRaw`` function.
    """

    def test_bothEmpty_returnsNone(self) -> None:
        """Both lists empty → ``None``."""
        assert _formatMemoriesBlockRaw([], []) is None

    def test_permanentSortedByTypeThenUpdatedAt(self) -> None:
        """Permanent section is sorted by ``type`` then ``updated_at``.

        Inputs are given out-of-order (preference before bio, older bio before
        newer bio); the rendered block must list them sorted.
        """
        older = _TS
        newer = _TS + datetime.timedelta(seconds=10)
        permanent = [
            _memoryDict(content="prefers dark mode", memType="preference", permanent=True, updated_at=newer),
            _memoryDict(content="is a nurse", memType="fact", permanent=True, updated_at=older),
            _memoryDict(content="bio older", memType="bio", permanent=True, updated_at=older),
            _memoryDict(content="bio newer", memType="bio", permanent=True, updated_at=newer),
        ]

        block = _formatMemoriesBlockRaw(permanent, [])

        assert block is not None
        lines = block.split("\n")
        # lines[0] = <user-memories>, [1] = Permanent:, then 4 type lines, then closing tag.
        assert lines[2] == "[bio] bio older"
        assert lines[3] == "[bio] bio newer"
        assert lines[4] == "[fact] is a nurse"
        assert lines[5] == "[preference] prefers dark mode"
        assert lines[6] == "</user-memories>"

    def test_tagsRenderAsHashSuffix_omittedWhenEmpty(self) -> None:
        """``[type] content #tag1 #tag2`` with tags; bare ``[type] content`` without."""
        permanent = [_memoryDict(content="lives in Berlin", memType="fact", permanent=True, tags=["geo", "europe"])]
        ephemeral = [_memoryDict(content="no tags here", memType="event", tags=[])]

        block = _formatMemoriesBlockRaw(permanent, ephemeral)

        assert block is not None
        assert "[fact] lives in Berlin #geo #europe" in block
        assert "[event] no tags here\n" in block + "\n"


# ---------------------------------------------------------------------------
# _resolveUserId (inherited from BaseBotHandler)
# ---------------------------------------------------------------------------


class TestResolveUserId:
    """Tests for :meth:`BaseBotHandler._resolveUserId`.

    The method is shared between the ``search_memories`` and ``search_messages``
    LLM tools. It is exercised here through :class:`UserMemoriesHandler` (a concrete
    subclass of :class:`BaseBotHandler`), constructed against a real in-memory
    database. The ``chatUsers`` repository attribute is swapped for a ``Mock``
    per test so the login-resolution path can be spied on without touching the DB.

    Covers:

    * Numeric ``user_id`` short-circuit (no DB lookup) — plain digits and
      ``@``-prefixed digits.
    * Login resolution (with and without ``@``) — both normalise to the
      ``@``-prefixed form the ``chat_users`` table stores.
    * Non-existent login → ``None``.
    * Empty / ``None`` input → ``None`` (no DB call).
    * DB exception → ``None`` (never raises).
    """

    async def test_numericString_returnsIntWithoutDbCall(self, testDatabase: Database) -> None:
        """A purely-numeric identifier is returned as int with no DB lookup.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock()
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        result = await handler._resolveUserId(chatId=100, userIdentifier="12345")

        assert result == 12345
        mockChatUsers.getChatUserByUsername.assert_not_called()

    async def test_numericStringWithAtPrefix_returnsIntWithoutDbCall(self, testDatabase: Database) -> None:
        """``"@12345"`` strips ``@`` then resolves as numeric user_id (no DB call).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock()
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        result = await handler._resolveUserId(chatId=100, userIdentifier="@12345")

        assert result == 12345
        mockChatUsers.getChatUserByUsername.assert_not_called()

    async def test_loginWithAt_resolvesViaDb(self, testDatabase: Database) -> None:
        """Login with ``@`` prefix → DB lookup with ``@``-prefixed username.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock(return_value={"user_id": 999})
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        result = await handler._resolveUserId(chatId=100, userIdentifier="@alice")

        assert result == 999
        mockChatUsers.getChatUserByUsername.assert_awaited_once_with(chatId=100, username="@alice")

    async def test_loginWithoutAt_prependsAtForDbLookup(self, testDatabase: Database) -> None:
        """Login without ``@`` → ``@`` is prepended before DB lookup.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock(return_value={"user_id": 999})
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        result = await handler._resolveUserId(chatId=100, userIdentifier="alice")

        assert result == 999
        mockChatUsers.getChatUserByUsername.assert_awaited_once_with(chatId=100, username="@alice")

    async def test_nonExistentLogin_returnsNone(self, testDatabase: Database) -> None:
        """Login not in DB → ``None``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock(return_value=None)
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        result = await handler._resolveUserId(chatId=100, userIdentifier="ghost")

        assert result is None
        mockChatUsers.getChatUserByUsername.assert_awaited_once_with(chatId=100, username="@ghost")

    async def test_emptyInput_returnsNone(self, testDatabase: Database) -> None:
        """Empty string → ``None`` (no DB call).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock()
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        result = await handler._resolveUserId(chatId=100, userIdentifier="")

        assert result is None
        mockChatUsers.getChatUserByUsername.assert_not_called()

    async def test_noneInput_returnsNone(self, testDatabase: Database) -> None:
        """``None`` → ``None`` (no DB call).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock()
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        result = await handler._resolveUserId(chatId=100, userIdentifier=None)

        assert result is None
        mockChatUsers.getChatUserByUsername.assert_not_called()

    async def test_dbException_returnsNone(self, testDatabase: Database) -> None:
        """DB exception → ``None`` (method never raises).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock(side_effect=RuntimeError("DB down"))
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        result = await handler._resolveUserId(chatId=100, userIdentifier="alice")

        assert result is None

    async def test_unicodeSuperscript_returnsNone(self, testDatabase: Database) -> None:
        """Unicode "other digit" value (``"²"`` U+00B2) → ``None`` (never raises).

        Regression for the ``isdigit()`` → ``isdecimal()`` fix: ``str.isdigit()``
        admits superscripts such as ``"²"`` that ``int()`` cannot parse, so the
        old ``clean.isdigit()`` check routed them into ``int(clean)`` and raised
        ``ValueError`` — breaking the never-raises contract of the LLM tools
        (notably ``search_messages``) whose call paths are unguarded by
        try/except. With ``clean.isdecimal()`` the value is NOT a decimal, so it
        falls through to the login path; the DB lookup finds no match and
        ``None`` is returned. A plain decimal still resolves directly — see
        :meth:`test_numericString_returnsIntWithoutDbCall`.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)
        mockChatUsers = Mock()
        mockChatUsers.getChatUserByUsername = AsyncMock(return_value=None)
        handler.db.chatUsers = mockChatUsers  # type: ignore[assignment]

        # Must not raise (a ValueError here means isdigit() was used instead of
        # isdecimal()).
        result = await handler._resolveUserId(chatId=100, userIdentifier="²")

        assert result is None


# ---------------------------------------------------------------------------
# getThreadByMessageForLLM — permanent-memory dedup across first-N + tail (I6)
# ---------------------------------------------------------------------------


class TestGetThreadByMessageForLLMMemoryDedup:
    """Regression tests for permanent-memory dedup across the pinned/tail blocks.

    Bug (I6): in :meth:`BaseBotHandler.getThreadByMessageForLLM` the first-N
    (pinned) block rendered its messages against a throwaway
    ``excludeMemoryIds=set()`` while the tail loop initialised a SEPARATE
    accumulator. Because the pinned block's memory IDs never propagated into
    the tail's set, a permanent memory shared between a pinned message and a
    tail message (the common case — same user, same thread) was injected TWICE
    into the LLM context. Memory injection is per-message (each
    :class:`EnsuredMessage` resolves its own ``metadata["memories"]`` compact
    IDs via ``cache.getMemoriesByIds`` at render time), so this is a real
    double injection.

    The fix shares a single ``excludedMemoryIds`` accumulator across both
    blocks: the pinned block still renders all of its memories (its exclusion
    set is empty when it renders) and then seeds the set so the tail loop
    skips the already-emitted IDs.

    The handler is exercised through :class:`UserMemoriesHandler` (a concrete
    :class:`BaseBotHandler` subclass). :class:`EnsuredMessage` uses
    ``__slots__``, so the per-row behaviour is driven by patching
    ``EnsuredMessage.fromDBChatMessage`` at the CLASS level to return
    controlled messages carrying a shared permanent memory ID.
    """

    _CHAT_ID = 100
    """Recipient chat id used by every constructed message/row."""

    _THREAD_ID = 0
    """Thread id (``DEFAULT_THREAD_ID``) used by every constructed row."""

    _ROOT_ID = 1001
    """Message id of the root (pinned, first-N) message."""

    _TAIL_ID = 1002
    """Message id of the tail message (the one ``getThreadByMessageForLLM`` is called for)."""

    _SHARED_MEM_ID = "mem-shared"
    """Compact permanent-memory id referenced by BOTH the pinned root and the tail."""

    _MEM_CONTENT = "UNIQUE_MEMORY_CONTENT_42"
    """Distinctive content of the shared memory; asserted to appear exactly once."""

    @classmethod
    def _makeMsg(cls, *, messageId: int, text: str) -> EnsuredMessage:
        """Build a real :class:`EnsuredMessage` for one thread row.

        Sender/recipient are identical across rows (same user, same chat) so a
        memory injected for that user is shared. No media is attached, so
        ``updateMediaContent`` early-returns without ever touching ``db``.

        Args:
            messageId: Row message id (root or tail).
            text: Message body text.

        Returns:
            A freshly constructed :class:`EnsuredMessage` with ``threadId`` set.
        """
        msg = EnsuredMessage(
            sender=MessageSender(id=7, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=cls._CHAT_ID, chatType=ChatType.PRIVATE),
            messageId=messageId,
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText=text,
        )
        msg.threadId = cls._THREAD_ID
        return msg


# ---------------------------------------------------------------------------
# STT branch in _processMediaV2 / _transcribeMedia
# ---------------------------------------------------------------------------


class TestProcessMediaV2STT:
    """Tests for the STT (Speech-to-Text) branch in ``_processMediaV2``.

    Validates the four integration points of the STT pipeline:

    1. **DONE cache-hit gate**: DONE → always early return (unconditional;
       retroactive STT transcription of previously-processed media is
       intentionally out of scope).
    2. **Status decision**: STT-eligible + gate on → ``MediaStatus.PENDING``.
    3. **STT scheduling**: background ``_transcribeMedia`` task via
       ``queueService``, ``ret.task`` is the STT task (mirrors the
       image-parsing path).
    4. **``_transcribeMedia`` terminalization**: download success/failure,
       STT success/failure, exception handling — row never left PENDING.

    Uses a real in-memory SQLite database (``testDatabase`` fixture) so that
    ``ensureMediaInGroup``, ``addMediaAttachment``, ``getMediaAttachment``,
    and ``updateMediaAttachment`` exercise real DB transitions end-to-end.  ``getChatSettings`` is mocked per-test to
    return a controlled :class:`ChatSettingsDict`; ``STTService.getInstance``
    is patched so the background task hits a mock ``transcribeMedia``.
    """

    _CHAT_ID = 300
    """Chat id used for every EnsuredMessage in these tests."""

    _MEDIA_ID = "voice-file-unique-id-001"
    """file_unique_id used for voice attachments."""

    _FILE_ID = "voice-platform-file-id-001"
    """Platform file id passed to downloadAttachment."""

    _MEDIA_GROUP_ID = "media-group-stt-test"
    """mediaGroupId attached to every EnsuredMessage (required by _processMediaV2)."""

    @staticmethod
    def _buildChatSettings(
        *,
        transcribeMedia: bool = False,
        saveAttachments: bool = False,
        parseAttachments: bool = False,
    ) -> ChatSettingsDict:
        """Build a :class:`ChatSettingsDict` with every key ``_processMediaV2`` reads.

        Production code subscripts ``chatSettings[KEY]`` directly (never
        ``.get()``), so every key the method touches must be present to
        avoid ``KeyError``.

        Args:
            transcribeMedia: Value for ``TRANSCRIBE_MEDIA``.
            saveAttachments: Value for ``SAVE_ATTACHMENTS``.
            parseAttachments: Value for ``PARSE_ATTACHMENTS``.

        Returns:
            A :class:`ChatSettingsDict` with deterministic test values.
        """
        return {
            ChatSettingsKey.TRANSCRIBE_MEDIA: ChatSettingsValue("true" if transcribeMedia else "false"),
            ChatSettingsKey.SAVE_ATTACHMENTS: ChatSettingsValue("true" if saveAttachments else "false"),
            ChatSettingsKey.SAVE_PREFIX: ChatSettingsValue(""),
            ChatSettingsKey.PARSE_ATTACHMENTS: ChatSettingsValue("true" if parseAttachments else "false"),
            ChatSettingsKey.PARSE_IMAGE_PROMPT: ChatSettingsValue("describe this image"),
        }

    @staticmethod
    def _makeEnsuredMessage(
        *,
        mediaGroupId: Optional[str] = _MEDIA_GROUP_ID,
    ) -> EnsuredMessage:
        """Build a minimal :class:`EnsuredMessage` with a ``mediaGroupId``.

        ``_processMediaV2`` raises ``ValueError`` when ``mediaGroupId`` is
        ``None``, so every test message must carry one.

        Args:
            mediaGroupId: The media group identifier (defaults to the class
                constant).

        Returns:
            A freshly constructed :class:`EnsuredMessage`.
        """
        return EnsuredMessage(
            sender=MessageSender(id=7, name="Alice", username="@alice"),
            recipient=MessageRecipient(
                id=TestProcessMediaV2STT._CHAT_ID,
                chatType=ChatType.PRIVATE,
            ),
            messageId=9001,
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            mediaGroupId=mediaGroupId,
        )

    @staticmethod
    def _makeMockConfigManager(*, sttEnabled: bool) -> Mock:
        """Build a ``ConfigManager`` stub whose ``getSttConfig`` reflects the STT flag.

        ``BaseBotHandler.__init__`` caches ``self._sttEnabled`` from
        ``configManager.getSttConfig().get("enabled", False)`` at
        construction time, so the mock must be set up **before** the handler
        is instantiated.

        Args:
            sttEnabled: Whether ``stt.enabled`` is ``True`` or ``False``.

        Returns:
            A ``Mock`` whose ``getBotConfig`` and ``getSttConfig`` return
            controlled dicts, and ``get(key, default)`` returns ``{}``.
        """
        cm = Mock()
        cm.getBotConfig = Mock(return_value={"token": "test_token", "owners": [123456]})
        cm.getSttConfig = Mock(return_value={"enabled": sttEnabled})
        cm.get = Mock(return_value={})
        return cm

    @pytest.fixture(autouse=True)
    def _resetSingletons(self) -> Generator[None, None, None]:
        """Reset ``STTService``, ``StorageService``, ``QueueService``, and
        ``CacheService`` singletons around every test in this class.

        Prevents state leakage from one test to the next. ``LLMService`` is
        already reset by the conftest autouse fixture.

        Yields:
            None.
        """
        STTService._instance = None
        StorageService._instance = None
        QueueService._instance = None
        CacheService._instance = None
        yield
        STTService._instance = None
        StorageService._instance = None
        QueueService._instance = None
        CacheService._instance = None

    async def _makeHandler(
        self,
        testDatabase: Database,
        *,
        sttEnabled: bool,
    ) -> UserMemoriesHandler:
        """Construct a :class:`UserMemoriesHandler` wired to a real in-memory DB.

        Resets ``CacheService``, injects the test database, and constructs
        the handler with a ``ConfigManager`` stub whose ``getSttConfig``
        reflects ``sttEnabled``.

        Args:
            testDatabase: Fresh in-memory :class:`Database` (``testDatabase``
                fixture).
            sttEnabled: Whether the ``[stt] enabled`` flag is on.

        Returns:
            A handler whose ``self.db`` is *testDatabase*.
        """
        CacheService._instance = None
        cache = CacheService.getInstance()
        await cache.injectDatabase(testDatabase)

        configManager = self._makeMockConfigManager(sttEnabled=sttEnabled)
        handler = UserMemoriesHandler(
            configManager=configManager,
            database=testDatabase,
            botProvider=BotProvider.TELEGRAM,
        )
        return handler

    # ------------------------------------------------------------------
    # Scenario 1: stt.enabled=false — STT gate off at config level
    # ------------------------------------------------------------------

    async def test_sttGateOff_configDisabled_noTranscription(self, testDatabase: Database) -> None:
        """``stt.enabled=false`` disables STT even when ``TRANSCRIBE_MEDIA=true``.

        The row is created as ``DONE`` (no PENDING/STT cycle).  No
        ``downloadAttachment`` call for STT, no background task scheduled.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=False)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"fake-audio")
        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(transcribeMedia=True),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        msg = self._makeEnsuredMessage()
        await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
        )

        assert capturedTasks == []

        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.DONE

    # ------------------------------------------------------------------
    # Scenario 2: stt.enabled=true but TRANSCRIBE_MEDIA=false
    # ------------------------------------------------------------------

    async def test_sttGateOff_chatSettingFalse_noTranscription(self, testDatabase: Database) -> None:
        """``TRANSCRIBE_MEDIA=false`` disables STT at the chat-settings level.

        Even though ``stt.enabled=true``, the double gate requires both
        conditions.  Row ends ``DONE``; no STT background task.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"fake-audio")
        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(transcribeMedia=False),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        msg = self._makeEnsuredMessage()
        await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
        )

        assert capturedTasks == []

        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.DONE

    # ------------------------------------------------------------------
    # Scenario 3: DONE + description → cache hit, no re-transcription
    # ------------------------------------------------------------------

    async def test_sttCacheHit_doneWithDescription_reuses(self, testDatabase: Database) -> None:
        """A ``DONE`` row that already has a transcript is reused (cache hit).

        ``STTService.transcribeMedia`` must NOT be called; ``downloadAttachment``
        must NOT be called for STT.  ``ret.task`` is the empty placeholder.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"fake-audio")
        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(transcribeMedia=True),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(
            return_value=STTOutcome(success=True, description="fresh transcript"),
        )

        # Pre-seed a DONE row with a description.
        await testDatabase.mediaAttachments.addMediaAttachment(
            fileUniqueId=self._MEDIA_ID,
            fileId=self._FILE_ID,
            mediaType=MessageType.VOICE,
            status=MediaStatus.DONE,
            description="existing transcript",
        )

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        ret = await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
        )

        assert ret.id == self._MEDIA_ID
        assert ret.task is not None
        assert capturedTasks == []
        mockSttService.transcribeMedia.assert_not_called()
        handler._bot.downloadAttachment.assert_not_called()

        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.DONE
        assert row["description"] == "existing transcript"

    # ------------------------------------------------------------------
    # Scenario 5: new media → full STT pipeline (PENDING → DONE)
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "mediaType", [MessageType.VIDEO, MessageType.VIDEO_NOTE, MessageType.VOICE, MessageType.AUDIO]
    )
    async def test_sttNewMedia_transcribesToDone(self, testDatabase: Database, mediaType: MessageType) -> None:
        """New STT-eligible media is transcribed end-to-end.

        Row is created ``PENDING``, background task is scheduled, and after
        the task completes the row is ``DONE`` with the transcript.

        Args:
            testDatabase: Fresh in-memory database fixture.
            mediaType: Parametrized STT-eligible :class:`MessageType`.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"fake-audio-data")
        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(transcribeMedia=True, parseAttachments=True),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(
            return_value=STTOutcome(success=True, description="hello world transcript"),
        )

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        ret = await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=mediaType,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
            metadata={"source": "test"},
        )

        assert ret.id == self._MEDIA_ID
        assert ret.task is not None
        assert len(capturedTasks) == 1

        # Row is PENDING immediately after _processMediaV2 returns.
        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.PENDING

        # Let the background task complete.
        await capturedTasks[0]

        mockSttService.transcribeMedia.assert_awaited_once()

        # Row is now DONE with the transcript.
        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.DONE
        assert row["description"] == "hello world transcript"

    # ------------------------------------------------------------------
    # Scenario 6: downloadAttachment returns None → FAILED
    # ------------------------------------------------------------------

    async def test_sttDownloadReturnsNone_terminalizesFailed(self, testDatabase: Database) -> None:
        """``downloadAttachment`` returning ``None`` terminalizes the row to ``FAILED``.

        ``STTService.transcribeMedia`` must NOT be called because the data
        never arrived.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=None)
        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(transcribeMedia=True, parseAttachments=True),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(
            return_value=STTOutcome(success=True, description="should not reach"),
        )

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
            metadata={"source": "test"},
        )

        assert len(capturedTasks) == 0
        mockSttService.transcribeMedia.assert_not_called()

        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.FAILED
        assert row["description"] is None

    # ------------------------------------------------------------------
    # Scenario 7: STTService returns FAILED → row FAILED
    # ------------------------------------------------------------------

    async def test_sttServiceReturnsFailed_terminalizesFailed(self, testDatabase: Database) -> None:
        """``STTService.transcribeMedia`` returning ``FAILED`` terminalizes the row.

        The ``errorCode`` is logged but NOT persisted — the row's description
        remains ``None``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"fake-audio")
        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(transcribeMedia=True, parseAttachments=True),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(
            return_value=STTOutcome(
                success=False,
                description=None,
                errorCode=STTErrorCode.SOURCE_TOO_LARGE,
            ),
        )

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
            metadata={"source": "test"},
        )

        assert len(capturedTasks) == 1
        await capturedTasks[0]

        mockSttService.transcribeMedia.assert_awaited_once()

        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.FAILED
        assert row["description"] is None

    # ------------------------------------------------------------------
    # Scenario 8: transcribeMedia raises → row FAILED (outer except)
    # ------------------------------------------------------------------

    async def test_sttTranscribeRaisesException_terminalizesFailed(self, testDatabase: Database) -> None:
        """An unhandled exception in ``transcribeMedia`` terminalizes the row.

        The outer ``except Exception`` in ``_transcribeMedia`` catches it
        and writes ``FAILED``.  No unhandled exception escapes to the caller.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"fake-audio")
        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(transcribeMedia=True, parseAttachments=True),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(side_effect=RuntimeError("provider exploded"))

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
            metadata={"source": "test"},
        )

        assert len(capturedTasks) == 1
        # The background task must not raise — await it to confirm.
        await capturedTasks[0]

        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.FAILED
        assert row["description"] is None

    # ------------------------------------------------------------------
    # Scenario 9: ret.task is the STT task (mirrors the image-parsing path)
    # ------------------------------------------------------------------

    async def test_sttRetTaskIsTheSttTask(self, testDatabase: Database) -> None:
        """``ret.task`` is the STT task (mirrors the image-parsing path).

        The LLM polls the DB (via ``_awaitMedia``, 300 s cap) instead of
        awaiting the transcription task directly.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"fake-audio")
        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(transcribeMedia=True, parseAttachments=True),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(
            return_value=STTOutcome(success=True, description="transcript"),
        )

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        ret = await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
            metadata={"source": "test"},
        )

        assert len(capturedTasks) == 1
        sttTask = capturedTasks[0]

        # ret.task must be the STT task object.
        assert ret.task is sttTask
        assert ret.task is not None
        await ret.task
        assert ret.task.done()

        # Clean up the background task.
        await sttTask

        # After the STT task completes the row must be DONE with transcript.
        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.DONE
        assert row["description"] == "transcript"

    # ------------------------------------------------------------------
    # Scenario 10: non-STT media (IMAGE) is unaffected by the STT gate
    # ------------------------------------------------------------------

    async def test_nonSttMedia_unaffected(self, testDatabase: Database) -> None:
        """IMAGE attachments bypass the STT gate entirely.

        With the STT gate on and ``PARSE_ATTACHMENTS=true``, an IMAGE
        should enter the image-parsing path (``downloadAttachment`` is
        called for parsing), NOT the STT scheduling path.  No STT
        background task is scheduled.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        # downloadAttachment returns None → image parsing sets FAILED.
        handler._bot.downloadAttachment = AsyncMock(return_value=None)
        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(
                transcribeMedia=True,
                parseAttachments=True,
            ),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(
            return_value=STTOutcome(success=True, description="should not be called"),
        )

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.IMAGE,
            mediaId="image-file-unique-id-002",
            fileId="image-platform-file-id-002",
        )

        # No STT task scheduled (IMAGE is not a STT-eligible media type).
        assert capturedTasks == []
        mockSttService.transcribeMedia.assert_not_called()

        # downloadAttachment was called for image parsing (not for STT).
        assert handler._bot.downloadAttachment.called

        # Image parsing attempted download, got None → FAILED.
        row = await testDatabase.mediaAttachments.getMediaAttachment("image-file-unique-id-002")
        assert row is not None
        assert row["status"] == MediaStatus.FAILED

    # ------------------------------------------------------------------
    # Scenario 12: orphaned PENDING row (older than timeout) is reclaimed
    # ------------------------------------------------------------------

    async def test_sttOrphanedPending_reclaims(self, testDatabase: Database) -> None:
        """A PENDING row older than ``PROCESSING_TIMEOUT`` is reclaimed for reprocessing.

        The orphan-check falls through (age exceeds the timeout), a new STT
        task is scheduled, and ``updated_at`` is refreshed.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"fake-audio")
        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(transcribeMedia=True, parseAttachments=True),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(
            return_value=STTOutcome(success=True, description="reclaimed transcript"),
        )

        # Pre-seed a PENDING row.  addMediaAttachment sets updated_at to now().
        await testDatabase.mediaAttachments.addMediaAttachment(
            fileUniqueId=self._MEDIA_ID,
            fileId=self._FILE_ID,
            mediaType=MessageType.VOICE,
            status=MediaStatus.PENDING,
            fileSize=None,
            description=None,
        )
        # Backdate updated_at so the row appears older than PROCESSING_TIMEOUT.
        provider = await testDatabase.manager.getProvider(readonly=False)
        oldTs = datetime.datetime(2020, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc).isoformat()
        await provider.execute(
            "UPDATE media_attachments SET updated_at = :ts WHERE file_unique_id = :id",
            {"ts": oldTs, "id": self._MEDIA_ID},
        )

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
            metadata={"source": "test"},
        )

        # A new STT task must have been scheduled (orphan reclaimed).
        assert len(capturedTasks) == 1
        await capturedTasks[0]

        mockSttService.transcribeMedia.assert_awaited_once()

        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.DONE
        assert row["description"] == "reclaimed transcript"

    # ------------------------------------------------------------------
    # Scenario 14: SAVE_ATTACHMENTS + TRANSCRIBE_MEDIA both on — compose
    # ------------------------------------------------------------------

    async def test_sttSaveAttachmentsAndStt_compose(self, testDatabase: Database) -> None:
        """Both ``SAVE_ATTACHMENTS`` and ``TRANSCRIBE_MEDIA`` active, gate on, new VOICE.

        The storage path runs first (download → ``storeAttachment`` → ``localUrl``),
        then the STT background task **reuses** the already-downloaded bytes instead
        of downloading again.  ``downloadAttachment`` is called exactly **once**
        total.  The row terminalizes to ``DONE`` with a transcript.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"fake-audio-bytes")

        # Mock storage so storeAttachment succeeds and returns a key.
        mockStorage = Mock()
        mockStorage.exists = Mock(return_value=False)
        mockStorage.store = Mock()
        handler.storage = mockStorage  # type: ignore[assignment]

        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(
                transcribeMedia=True,
                parseAttachments=True,
                saveAttachments=True,
            ),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(
            return_value=STTOutcome(success=True, description="composed transcript"),
        )

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        ret = await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
        )

        assert ret.id == self._MEDIA_ID

        # Storage happened: downloadAttachment called by SAVE path.
        assert handler._bot.downloadAttachment.call_count >= 1
        mockStorage.store.assert_called_once()
        mockStorage.exists.assert_called_once()

        # Row is PENDING | DONE immediately (STT path sets PENDING).
        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] in [MediaStatus.PENDING, MediaStatus.DONE]
        assert row["local_url"] is not None  # localUrl was written by storeAttachment.

        # STT task was scheduled.
        assert len(capturedTasks) == 1

        # Let the background task complete.
        await capturedTasks[0]

        # downloadAttachment called exactly ONCE total — the STT task reused
        # the SAVE-downloaded bytes via preloadedData (single download).
        assert handler._bot.downloadAttachment.call_count == 1

        mockSttService.transcribeMedia.assert_awaited_once()

        # Row is now DONE with transcript.
        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.DONE
        assert row["description"] == "composed transcript"

    # ------------------------------------------------------------------
    # Scenario 14b: SAVE_ATTACHMENTS off + TRANSCRIBE_MEDIA on → single
    #   download inside the STT task
    # ------------------------------------------------------------------

    async def test_sttSaveOff_downloadsInTask(self, testDatabase: Database) -> None:
        """``SAVE_ATTACHMENTS=false`` + ``TRANSCRIBE_MEDIA=true``: the STT task
        downloads the attachment itself (``preloadedData`` is ``None``).

        ``downloadAttachment`` must be called exactly **once** (by the STT
        background task, not by SAVE).  The row terminalizes to ``DONE`` with
        a transcript.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"fake-audio-data")

        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(
                transcribeMedia=True,
                parseAttachments=True,
                saveAttachments=False,
            ),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(
            return_value=STTOutcome(success=True, description="stt-only transcript"),
        )

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        ret = await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
        )

        assert ret.id == self._MEDIA_ID

        # STT task was scheduled.
        assert len(capturedTasks) == 1

        # Let the background task complete.
        await capturedTasks[0]

        # downloadAttachment called exactly once (by the STT task, not SAVE).
        assert handler._bot.downloadAttachment.call_count == 1

        mockSttService.transcribeMedia.assert_awaited_once()

        # Row is now DONE with transcript.
        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.DONE
        assert row["description"] == "stt-only transcript"

    # ------------------------------------------------------------------
    # Scenario 14c: preloadedData=b"" (empty but not None) — reuses, not
    #   re-downloads.  Locks in the ``is not None`` vs truthiness guard.
    # ------------------------------------------------------------------

    async def test_sttPreloadedEmptyBytes_reusedNotRedownloaded(self, testDatabase: Database) -> None:
        """Empty bytes (``b""``) from SAVE are reused by STT, not re-downloaded.

        ``downloadAttachment`` returns ``b""`` (falsy but not ``None``).  The
        SAVE path stores it, then the STT task receives it as
        ``preloadedData``.  Because ``_transcribeMedia`` guards on
        ``if preloadedData is not None:`` (not truthiness), it reuses the
        empty bytes instead of re-downloading.  ``downloadAttachment`` must
        be called exactly **once** total.

        If anyone changes the guard to ``if preloadedData:``, ``b""`` is
        falsy so the STT task would re-download, making ``call_count == 2``
        and this test fails — catching the regression.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"")

        # Mock storage so storeAttachment succeeds and returns a key.
        mockStorage = Mock()
        mockStorage.exists = Mock(return_value=False)
        mockStorage.store = Mock()
        handler.storage = mockStorage  # type: ignore[assignment]

        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(
                transcribeMedia=True,
                parseAttachments=True,
                saveAttachments=True,
            ),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        # Empty audio → STT will likely return FAILED / NO_AUDIO; that's fine.
        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(
            return_value=STTOutcome(success=False, description=None, errorCode=STTErrorCode.NO_AUDIO),
        )

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        ret = await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
        )

        assert ret.id == self._MEDIA_ID
        assert len(capturedTasks) == 1

        # Let the background task complete.
        await capturedTasks[0]

        # downloadAttachment called exactly ONCE — the STT task reused b""
        # via preloadedData (is not None guard, not truthiness).
        assert handler._bot.downloadAttachment.call_count == 1

        mockSttService.transcribeMedia.assert_awaited_once()

        # Row terminalizes to FAILED (empty audio is not transcribable).
        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.FAILED

    # ------------------------------------------------------------------
    # Scenario 15: DONE + no description + gate off → stays DONE
    # ------------------------------------------------------------------

    async def test_sttDoneNoDescription_gateOff_staysDone(self, testDatabase: Database) -> None:
        """A ``DONE`` row without transcript stays ``DONE`` when ``needProcessSTT`` is False.

        ``stt.enabled=true`` + STT-eligible media type, but
        ``TRANSCRIBE_MEDIA=false`` → ``needProcessSTT=False``.  The
        short-circuit in the DONE case returns early; no task is scheduled
        and the row is not reprocessed.

        Closes the DONE-case matrix: desc+gate-on, no-desc+gate-on,
        no-desc+gate-off.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await self._makeHandler(testDatabase, sttEnabled=True)
        handler._bot = Mock()
        handler._bot.downloadAttachment = AsyncMock(return_value=b"fake-audio")
        handler.getChatSettings = AsyncMock(  # type: ignore[assignment]
            return_value=self._buildChatSettings(transcribeMedia=False),
        )

        capturedTasks: list[asyncio.Task] = []

        async def captureTask(task: asyncio.Task) -> None:
            capturedTasks.append(task)

        handler.queueService.addBackgroundTask = AsyncMock(side_effect=captureTask)  # type: ignore[assignment]

        mockSttService = Mock()
        mockSttService.transcribeMedia = AsyncMock(
            return_value=STTOutcome(success=True, description="should not reach"),
        )

        # Pre-seed a DONE row WITHOUT a description.
        await testDatabase.mediaAttachments.addMediaAttachment(
            fileUniqueId=self._MEDIA_ID,
            fileId=self._FILE_ID,
            mediaType=MessageType.VOICE,
            status=MediaStatus.DONE,
            description=None,
        )

        msg = self._makeEnsuredMessage()
        STTService._instance = mockSttService
        ret = await handler._processMediaV2(
            ensuredMessage=msg,
            mediaType=MessageType.VOICE,
            mediaId=self._MEDIA_ID,
            fileId=self._FILE_ID,
        )

        assert ret.id == self._MEDIA_ID
        assert ret.task is not None
        assert capturedTasks == []
        mockSttService.transcribeMedia.assert_not_called()

        row = await testDatabase.mediaAttachments.getMediaAttachment(self._MEDIA_ID)
        assert row is not None
        assert row["status"] == MediaStatus.DONE
        assert row["description"] is None


class _ModelInfoDict(TypedDict, total=False):
    """``getModelInfo`` payload for one mocked model-catalog entry.

    Keys mirror the fields the model-tier gate actually reads; all optional
    so a tier-less model is expressed by omitting ``tier``.
    """

    tier: str
    support_text: bool


class TestGetChatSettingsModelTierFilterRegression:
    """Pins the model-tier gate in ``BaseBotHandler.getChatSettings``.

    Regression for the silently-invisible-model bug: a MODEL-type setting
    pointing at a model whose ``tier`` is missing or invalid used to be
    dropped from the merged settings for every chat (``ChatTier.fromStr``
    returned ``None``), with no diagnostic. Missing/invalid tiers must now
    resolve to ``bot-owner``: kept for bot-owner-tier chats, dropped for
    lower tiers, with a logged warning naming the model and the raw invalid
    value.
    """

    _CHAT_ID = 100
    """Chat ID used for the mocked per-chat settings."""

    @staticmethod
    def _makeLlmManager(modelInfos: Dict[str, Optional[_ModelInfoDict]]) -> Mock:
        """Build a mock LLMManager serving *modelInfos*.

        Args:
            modelInfos: Mapping of model name to ``getModelInfo`` payload.

        Returns:
            Mock with ``listModels``/``getModelInfo`` wired to *modelInfos*.
        """
        manager = Mock(spec=LLMManager)
        manager.listModels = Mock(return_value=list(modelInfos.keys()))
        manager.getModelInfo = Mock(side_effect=lambda name: modelInfos.get(name))
        return manager

    @staticmethod
    def _tierGateChatSettings(baseTier: str, modelName: str) -> ChatSettingsDict:
        """Build per-chat settings pointing ``CHAT_MODEL`` at *modelName*.

        ``updatedBy=7`` (a non-owner user) so the bot-owner bypass in the tier
        gate does not mask the model-tier comparison under test.

        Args:
            baseTier: Value for ``BASE_TIER``.
            modelName: Value for ``CHAT_MODEL``.

        Returns:
            ChatSettingsDict served by the mocked ``cache.getChatSettings``.
        """
        return {
            ChatSettingsKey.BASE_TIER: ChatSettingsValue(baseTier, updatedBy=7),
            ChatSettingsKey.CHAT_MODEL: ChatSettingsValue(modelName, updatedBy=7),
        }

    async def _getFilteredSettings(
        self,
        caplog: pytest.LogCaptureFixture,
        *,
        modelInfos: Dict[str, Optional[_ModelInfoDict]],
        baseTier: str,
        modelName: str,
    ) -> ChatSettingsDict:
        """Run the real ``getChatSettings`` tier filter over a mocked chat.

        Args:
            caplog: pytest log-capture fixture (WARNING level is enabled).
            modelInfos: Mock model catalog for the LLM manager.
            baseTier: ``BASE_TIER`` of the chat.
            modelName: Model the chat's ``CHAT_MODEL`` setting points at.

        Returns:
            The filtered settings dict produced by ``getChatSettings``.
        """
        llmManager = self._makeLlmManager(modelInfos)
        llmService = Mock()
        llmService.getLLMManager = Mock(return_value=llmManager)
        cache = Mock()
        cache.getCachedChatSettings = Mock(return_value=None)
        cache.getChatSettings = AsyncMock(return_value=self._tierGateChatSettings(baseTier, modelName))
        cache.getDefaultChatSettings = Mock(return_value={})
        cache.cacheChatSettings = Mock(return_value=None)

        with (
            patch.object(CacheService, "getInstance", return_value=cache),
            patch.object(QueueService, "getInstance", return_value=Mock()),
            patch.object(StorageService, "getInstance", return_value=Mock()),
            patch.object(LLMService, "getInstance", return_value=llmService),
        ):
            handler = UserMemoriesHandler(
                configManager=_makeConfigManager(),
                database=Mock(spec=Database),
                botProvider=BotProvider.TELEGRAM,
            )

        bot = Mock()
        bot.isBotOwner = Mock(return_value=False)
        handler.injectBot(bot)

        with caplog.at_level(logging.WARNING):
            return await handler.getChatSettings(self._CHAT_ID, returnDefault=False)

    async def test_ownerTierChatKeepsInvalidTierModelSetting_withWarning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A bot-owner-tier chat keeps a MODEL setting pointing at a model
        with an invalid tier, and the invalid value is logged.

        Before the fix the setting was silently dropped even for owner-tier
        chats.

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        result = await self._getFilteredSettings(
            caplog,
            modelInfos={"invalid-tier-model": {"tier": "bot_owner", "support_text": True}},
            baseTier="bot-owner",
            modelName="invalid-tier-model",
        )

        assert ChatSettingsKey.CHAT_MODEL in result
        assert result[ChatSettingsKey.CHAT_MODEL].toStr() == "invalid-tier-model"
        assert "invalid-tier-model" in caplog.text
        assert "has invalid tier 'bot_owner'" in caplog.text

    async def test_freeChatDropsInvalidTierModelSetting_withWarning(self, caplog: pytest.LogCaptureFixture) -> None:
        """A free-tier chat has a MODEL setting pointing at an invalid-tier
        model dropped, and the invalid value is logged.

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        result = await self._getFilteredSettings(
            caplog,
            modelInfos={"invalid-tier-model": {"tier": "bot_owner", "support_text": True}},
            baseTier="free",
            modelName="invalid-tier-model",
        )

        assert ChatSettingsKey.CHAT_MODEL not in result
        assert "has invalid tier 'bot_owner'" in caplog.text

    async def test_ownerTierChatKeepsNoTierModelSetting_silently(self, caplog: pytest.LogCaptureFixture) -> None:
        """A bot-owner-tier chat keeps a MODEL setting pointing at a model
        with NO tier key, without any warning (documented default).

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        result = await self._getFilteredSettings(
            caplog,
            modelInfos={"no-tier-model": {"support_text": True}},
            baseTier="bot-owner",
            modelName="no-tier-model",
        )

        assert ChatSettingsKey.CHAT_MODEL in result
        assert result[ChatSettingsKey.CHAT_MODEL].toStr() == "no-tier-model"
        assert "has invalid tier" not in caplog.text

    async def test_paidTierChatKeepsPaidModelSetting(self, caplog: pytest.LogCaptureFixture) -> None:
        """A valid ``"paid"`` tier model keeps its existing filtering
        behaviour (paid-and-better chats keep the setting).

        Args:
            caplog: pytest log-capture fixture.

        Returns:
            None
        """
        result = await self._getFilteredSettings(
            caplog,
            modelInfos={"paid-model": {"tier": "paid", "support_text": True}},
            baseTier="paid",
            modelName="paid-model",
        )

        assert ChatSettingsKey.CHAT_MODEL in result
        assert result[ChatSettingsKey.CHAT_MODEL].toStr() == "paid-model"
        assert "has invalid tier" not in caplog.text


# ---------------------------------------------------------------------------
# getLLMRequestSessionId — session-id shape via lib.ai.session.buildSessionId
# ---------------------------------------------------------------------------


class TestGetLLMRequestSessionId:
    """Tests for :meth:`BaseBotHandler.getLLMRequestSessionId`.

    The helper resolves the thread root the same way ``saveChatMessage`` /
    ``getThreadByMessageForLLM`` do (the DB row's ``root_message_id`` when
    present, the message's own id otherwise) and formats the session id via
    :func:`lib.ai.session.buildSessionId`. The id feeds the OpenCode Go
    ``x-opencode-session`` header, so the exact shape is pinned here:
    ``gromozeka-<chatId>-<messageId>``, with negative group chat ids
    producing the historical double dash (``gromozeka--100123-...``).

    Exercised through :class:`UserMemoriesHandler` (a concrete
    :class:`BaseBotHandler` subclass) against the real in-memory database;
    the ``chatMessages`` repository is swapped for a ``Mock`` where a stored
    thread root (or a DB failure) must be simulated.
    """

    @staticmethod
    def _makeMessage(*, chatId: int, messageId: int) -> EnsuredMessage:
        """Build a Telegram-platform :class:`EnsuredMessage`.

        Args:
            chatId: Recipient chat id (negative for groups).
            messageId: Message id (int for Telegram).

        Returns:
            A freshly constructed :class:`EnsuredMessage`.
        """
        return EnsuredMessage(
            sender=MessageSender(id=7, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=chatId, chatType=ChatType.GROUP if chatId < 0 else ChatType.PRIVATE),
            messageId=messageId,
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="hello",
        )

    async def test_noDbRow_fallsBackToOwnMessageId(self, testDatabase: Database) -> None:
        """A message missing from the DB uses its own id as the session tail.

        The DB lookup returns no row (real in-memory database, nothing
        seeded), so the session id is built from the message's own id.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)

        result = await handler.getLLMRequestSessionId(self._makeMessage(chatId=100, messageId=456))

        assert result == "gromozeka-100-456"

    async def test_storedRoot_usedAsSessionTail(self, testDatabase: Database) -> None:
        """A stored ``root_message_id`` replaces the message's own id.

        Args:
            testDatabase: Fresh in-memory database fixture (used to build
                the handler; the ``chatMessages`` repository is swapped for
                a mock afterwards).
        """
        handler = await _makeHandler(testDatabase)
        mockChatMessages = Mock()
        mockChatMessages.getChatMessageByMessageId = AsyncMock(
            return_value=cast(ChatMessageDict, {"root_message_id": MessageId(1001)})
        )
        handler.db.chatMessages = mockChatMessages  # type: ignore[assignment]

        result = await handler.getLLMRequestSessionId(self._makeMessage(chatId=100, messageId=456))

        assert result == "gromozeka-100-1001"

    async def test_negativeGroupChatId_doubleDashPreserved(self, testDatabase: Database) -> None:
        """A negative group chat id yields the historical double dash.

        Pins the byte-identity requirement: the sanitizer behind
        ``buildSessionId`` must not strip or collapse dashes, so
        ``-100123`` produces ``gromozeka--100123-456`` exactly like the old
        f-string did.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeHandler(testDatabase)

        result = await handler.getLLMRequestSessionId(self._makeMessage(chatId=-100123, messageId=456))

        assert result == "gromozeka--100123-456"

    async def test_dbFailure_fallsBackToOwnMessageId(self, testDatabase: Database) -> None:
        """A DB error falls back to the message's own id (never raises).

        Args:
            testDatabase: Fresh in-memory database fixture (used to build
                the handler; the ``chatMessages`` repository is swapped for
                a mock afterwards).
        """
        handler = await _makeHandler(testDatabase)
        mockChatMessages = Mock()
        mockChatMessages.getChatMessageByMessageId = AsyncMock(side_effect=RuntimeError("DB down"))
        handler.db.chatMessages = mockChatMessages  # type: ignore[assignment]

        result = await handler.getLLMRequestSessionId(self._makeMessage(chatId=100, messageId=456))

        assert result == "gromozeka-100-456"


# ---------------------------------------------------------------------------
# D1/D2 session/consumer ids threaded into the LLMService boundary
# ---------------------------------------------------------------------------


class TestLLMCallSiteSessionIds:
    """Session/consumer id threading into the ``BaseBotHandler`` lib/ai call sites.

    Pins the D1/D2 wiring: both ``condenseContext`` calls inside
    :meth:`BaseBotHandler.getThreadByMessageForLLM` must forward the canonical
    conversation session id (:meth:`BaseBotHandler.getLLMRequestSessionId`,
    ``gromozeka-<chatId>-<rootMessageId>``) plus ``consumerId=str(chatId)`` for
    condensing-stats attribution, and the one-shot media parse in
    :meth:`BaseBotHandler._parseImage` must forward a media-scoped session id
    built from the attachment's persistent ``file_unique_id``
    (:func:`lib.ai.session.buildSessionId`).

    Exercised through :class:`UserMemoriesHandler` (a concrete
    :class:`BaseBotHandler` subclass). The ``chatMessages`` /
    ``mediaAttachments`` repositories are swapped for mocks and
    ``EnsuredMessage.fromDBChatMessage`` / ``EnsuredMessage.toModelMessageList``
    are patched at class level (``EnsuredMessage`` uses ``__slots__``).
    """

    _CHAT_ID = 100
    """Recipient chat id (positive → private chat)."""

    _ROOT_ID = 1001
    """Message id of the thread root (the session-id tail)."""

    _TAIL_ID = 1002
    """Message id of the tail message ``getThreadByMessageForLLM`` is called for."""

    @staticmethod
    def _makeRow(*, messageId: int, messageText: str) -> ChatMessageDict:
        """Build a ``ChatMessageDict`` row belonging to the test thread.

        Args:
            messageId: Row message id (root or tail).
            messageText: Message body text.

        Returns:
            A dict matching the ``ChatMessageDict`` shape with all required keys.
        """
        rowDate = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        return {
            "chat_id": TestLLMCallSiteSessionIds._CHAT_ID,
            "message_id": MessageId(messageId),
            "date": rowDate,
            "user_id": 7,
            "reply_id": None,
            "thread_id": 0,
            "root_message_id": MessageId(TestLLMCallSiteSessionIds._ROOT_ID),
            "message_text": messageText,
            "message_type": "text",
            "message_category": MessageCategory.USER,
            "quote_text": None,
            "media_id": None,
            "created_at": rowDate,
            "metadata": "{}",
            "markup": "",
            "media_group_id": None,
            "username": "alice",
            "full_name": "alice",
        }

    @staticmethod
    def _makeChatSettings() -> ChatSettingsDict:
        """Build chat settings covering every key ``getThreadByMessageForLLM`` reads.

        Production code subscripts ``chatSettings[KEY]`` directly (never
        ``.get()``), so every key on the condensing path must be present.
        ``CHAT_MODEL`` / ``CONDENSING_MODEL`` are wrapped in real
        :class:`ChatSettingsValue` instances; ``ChatSettingsValue.toModel`` is
        patched per-test to avoid the real LLM manager.

        Returns:
            A complete :class:`ChatSettingsDict` with deterministic values.
        """
        return {
            ChatSettingsKey.CHAT_PROMPT: ChatSettingsValue("CHAT_PROMPT_BASE"),
            ChatSettingsKey.CHAT_PROMPT_SUFFIX: ChatSettingsValue("CHAT_PROMPT_SUFFIX_BASE"),
            ChatSettingsKey.LLM_MESSAGE_FORMAT: ChatSettingsValue("text"),
            ChatSettingsKey.MEMORY_ENABLED: ChatSettingsValue("false"),
            ChatSettingsKey.CHAT_MODEL: ChatSettingsValue("dummy-chat-model"),
            ChatSettingsKey.CONDENSING_MODEL: ChatSettingsValue("dummy-condensing-model"),
            ChatSettingsKey.CONDENSING_PROMPT: ChatSettingsValue("condense prompt body"),
            ChatSettingsKey.CONDENSING_SYSTEM_PROMPT: ChatSettingsValue("condense sys body"),
        }

    @staticmethod
    def _makeEnsuredMessage() -> EnsuredMessage:
        """Build the tail :class:`EnsuredMessage` the thread is resolved for.

        Returns:
            A constructed :class:`EnsuredMessage` for the tail message.
        """
        return EnsuredMessage(
            sender=MessageSender(id=7, name="Alice", username="@alice"),
            recipient=MessageRecipient(id=TestLLMCallSiteSessionIds._CHAT_ID, chatType=ChatType.PRIVATE),
            messageId=TestLLMCallSiteSessionIds._TAIL_ID,
            date=datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            messageText="tail",
        )

    async def testCondenseContextCallsPassSessionIdAndConsumerId(self, testDatabase: Database) -> None:
        """Both condense passes share the conversation session id and chat consumer.

        The thread token estimate is forced above the condense threshold so
        ``getThreadByMessageForLLM`` runs the first condense pass AND the
        re-condense of the cache (the mocked token estimator always reports an
        overflow). Each ``condenseContext`` call must carry
        ``sessionId="gromozeka-<chatId>-<rootMessageId>"`` (resolved through the
        stored ``root_message_id``) and ``consumerId=str(chatId)``.

        Args:
            testDatabase: Fresh in-memory database fixture (used to build the
                handler; the ``chatMessages`` repository is swapped for a mock
                afterwards).
        """
        handler = await _makeHandler(testDatabase)

        tailRow = self._makeRow(messageId=self._TAIL_ID, messageText="tail")
        rootRow = self._makeRow(messageId=self._ROOT_ID, messageText="root")
        mockRepo = Mock()
        mockRepo.getChatMessageByMessageId = AsyncMock(return_value=tailRow)
        mockRepo.getChatMessagesByRootId = AsyncMock(return_value=[rootRow, tailRow])
        mockRepo.updateChatMessageMetadata = AsyncMock()
        handler.db.chatMessages = mockRepo  # type: ignore[assignment]
        handler.getChatSettings = AsyncMock(return_value=self._makeChatSettings())  # type: ignore[method-assign]
        condenseMock = AsyncMock(return_value=([ModelMessage(role="user", content="SUMMARY")], {}))
        handler.llmService.condenseContext = condenseMock  # type: ignore[method-assign]

        async def fakeFromDB(dbRow: ChatMessageDict, db: Database) -> EnsuredMessage:
            """Stand in for ``EnsuredMessage.fromDBChatMessage``.

            Args:
                dbRow: The DB row to render.
                db: Database (unused, mirrors the real signature).

            Returns:
                A plain :class:`EnsuredMessage` built from the row.
            """
            return EnsuredMessage(
                sender=MessageSender(id=7, name="Alice", username="@alice"),
                recipient=MessageRecipient(id=dbRow["chat_id"], chatType=ChatType.PRIVATE),
                messageId=dbRow["message_id"],
                date=dbRow["date"],
                messageText=dbRow["message_text"],
            )

        # Force the overflow: maxTokens = contextSize * 0.5 = 50, estimator
        # always reports 1000 → first pass runs AND the cache re-condense runs.
        overflowModel = Mock()
        overflowModel.contextSize = 100
        overflowModel.getEstimateTokensCount = Mock(return_value=1000)

        em = self._makeEnsuredMessage()
        with (
            patch.object(EnsuredMessage, "fromDBChatMessage", AsyncMock(side_effect=fakeFromDB)),
            patch.object(
                EnsuredMessage,
                "toModelMessageList",
                AsyncMock(return_value=[ModelMessage(role="user", content="body")]),
            ),
            patch.object(ChatSettingsValue, "toModel", Mock(return_value=overflowModel)),
        ):
            await handler.getThreadByMessageForLLM(em)

        assert condenseMock.await_count == 2
        for call in condenseMock.await_args_list:
            assert call.kwargs["sessionId"] == f"gromozeka-{self._CHAT_ID}-{self._ROOT_ID}"
            assert call.kwargs["consumerId"] == str(self._CHAT_ID)

    async def testParseImageGenerateTextPassesMediaSessionId(self, testDatabase: Database) -> None:
        """The one-shot image parse uses a media-scoped session id.

        ``_parseImage`` must forward ``sessionId=buildSessionId("media",
        fileUniqueId)`` — the attachment's persistent id, not the conversation
        session — so repeated parses of the same media reuse one cache bucket.

        Args:
            testDatabase: Fresh in-memory database fixture (used to build the
                handler; the ``mediaAttachments`` repository is swapped for a
                mock afterwards).
        """
        handler = await _makeHandler(testDatabase)
        handler.getChatSettings = AsyncMock(  # type: ignore[method-assign]
            return_value={
                ChatSettingsKey.IMAGE_PARSING_MODEL: ChatSettingsValue("dummy-image-model"),
                ChatSettingsKey.IMAGE_PARSING_FALLBACK_MODEL: ChatSettingsValue("dummy-image-fallback"),
            }
        )
        mockMediaRepo = Mock()
        mockMediaRepo.updateMediaAttachment = AsyncMock()
        handler.db.mediaAttachments = mockMediaRepo  # type: ignore[assignment]
        generateMock = AsyncMock(
            return_value=ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText="a cat on a sofa")
        )
        handler.llmService.generateText = generateMock  # type: ignore[method-assign]

        result = await handler._parseImage(
            self._makeEnsuredMessage(),
            "file-unique-123",
            [ModelMessage(role="user", content="image payload")],
        )

        assert result is True
        generateMock.assert_awaited_once()
        assert generateMock.call_args.kwargs["sessionId"] == "gromozeka-media-file-unique-123"
        mockMediaRepo.updateMediaAttachment.assert_awaited_once()
