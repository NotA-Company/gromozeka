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

import datetime
import types
from typing import Generator, List, Optional, cast
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
    UserMetadataDict,
)
from internal.database import Database
from internal.database.models import MemoryType, UserMemorySource
from internal.database.repositories.user_memories import UserMemoryDict
from internal.services.cache import CacheService

# ---------------------------------------------------------------------------
# Singleton hygiene
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _resetCacheServiceSingleton() -> Generator[None, None, None]:
    """Reset the ``CacheService`` singleton around every test in this module.

    Keeps the closed in-memory database from one test from leaking into the
    next via the ``CacheService`` singleton (which is not reset by
    ``tests/conftest.py``).

    Yields:
        None.
    """
    CacheService._instance = None
    yield
    CacheService._instance = None


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
            "embedding_model": None,
            "embedding_dimensions": None,
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

    async def test_sharedPermanentMemory_renderedOnceNotTwice(self, testDatabase: Database) -> None:
        """A permanent memory shared by a pinned root and a tail message is injected once.

        Constructs a condensed thread whose root (pinned by the first-N block)
        and tail message both reference the same permanent memory id, drives
        :meth:`getThreadByMessageForLLM`, and asserts the resolved memory
        content appears EXACTLY ONCE across the assembled messages. Before the
        fix the content appeared twice (once per render path).

        Args:
            testDatabase: Fresh in-memory database fixture (used to build the
                handler; ``chatMessages`` and ``cache`` are swapped for mocks).
        """
        handler = await _makeHandler(testDatabase)

        # Pinned root: carries a condensedThread cache (so the first-N block
        # executes) AND a permanent memory id shared with the tail.
        rootMsg = self._makeMsg(messageId=self._ROOT_ID, text="root message body")
        rootMsg.metadata["memories"] = {  # type: ignore[assignment]
            "permanentIds": [self._SHARED_MEM_ID],
            "shortTermIds": [],
        }
        rootMsg.metadata["condensedThread"] = [  # type: ignore[assignment]
            {
                "text": "condensed summary of earlier discussion",
                "tillMessageId": self._ROOT_ID,
                "tillTS": datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc).timestamp(),
            }
        ]

        # Tail message from the SAME user sharing the SAME permanent memory id.
        tailMsg = self._makeMsg(messageId=self._TAIL_ID, text="tail message body")
        tailMsg.metadata["memories"] = {  # type: ignore[assignment]
            "permanentIds": [self._SHARED_MEM_ID],
            "shortTermIds": [],
        }

        # cache resolves the shared id to content for every render.
        cache = Mock()
        cache.getMemoriesByIds = AsyncMock(
            return_value={self._SHARED_MEM_ID: {"type": MemoryType.FACT, "content": self._MEM_CONTENT, "tags": []}}
        )
        handler.cache = cache  # type: ignore[assignment]

        # DB rows — only the fields read directly by getThreadByMessageForLLM
        # are populated; the EnsuredMessage objects are returned by the patched
        # fromDBChatMessage (keyed on message_id).
        currentDbRow = {
            "chat_id": self._CHAT_ID,
            "message_id": self._TAIL_ID,
            "root_message_id": self._ROOT_ID,
            "thread_id": self._THREAD_ID,
        }
        rootRow = {
            "chat_id": self._CHAT_ID,
            "message_id": self._ROOT_ID,
            "root_message_id": self._ROOT_ID,
            "thread_id": self._THREAD_ID,
            "message_category": "user",
            "date": datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
        }
        tailRow = {
            "chat_id": self._CHAT_ID,
            "message_id": self._TAIL_ID,
            "root_message_id": self._ROOT_ID,
            "thread_id": self._THREAD_ID,
            "message_category": "user",
            "date": datetime.datetime(2026, 1, 2, 12, 0, 0, tzinfo=datetime.timezone.utc),
        }
        mockChatMessages = Mock()
        mockChatMessages.getChatMessageByMessageId = AsyncMock(return_value=currentDbRow)
        mockChatMessages.getChatMessagesByRootId = AsyncMock(return_value=[rootRow, tailRow])
        handler.db.chatMessages = mockChatMessages  # type: ignore[assignment]

        # Chat settings: MEMORY_ENABLED on + JSON format (so memories render).
        # CHAT_MODEL.toModel() returns a mock model so the token-budget check
        # returns early without actually condensing (keepFirstN/keepLastN
        # accounting untouched). The dict carries every key the production
        # path subscripts directly (no .get()).
        mockModel = Mock()
        mockModel.contextSize = 1_000_000
        mockModel.getEstimateTokensCount = Mock(return_value=0)
        chatModelValue = Mock(spec=ChatSettingsValue)
        chatModelValue.toModel = Mock(return_value=mockModel)
        chatSettings: ChatSettingsDict = {
            ChatSettingsKey.LLM_MESSAGE_FORMAT: ChatSettingsValue("json"),
            ChatSettingsKey.MEMORY_ENABLED: ChatSettingsValue("true"),
            ChatSettingsKey.CHAT_PROMPT: ChatSettingsValue("system prompt"),
            ChatSettingsKey.CHAT_PROMPT_SUFFIX: ChatSettingsValue(""),
            ChatSettingsKey.CHAT_MODEL: chatModelValue,  # type: ignore[dict-item]
        }
        handler.getChatSettings = AsyncMock(return_value=chatSettings)  # type: ignore[method-assign]

        async def fakeFromDBChatMessage(dbRow: dict, db: Database) -> EnsuredMessage:
            """Patch stand-in mapping a dbRow to its controlled EnsuredMessage.

            Args:
                dbRow: The raw DB row (keyed on ``message_id``).
                db: Database wrapper (ignored — the controlled messages have no media).

            Returns:
                The :class:`EnsuredMessage` (root or tail) for the given row.
            """
            return rootMsg if dbRow["message_id"] == self._ROOT_ID else tailMsg

        inputMsg = self._makeMsg(messageId=self._TAIL_ID, text="current message")

        with patch.object(EnsuredMessage, "fromDBChatMessage", fakeFromDBChatMessage):
            result = await handler.getThreadByMessageForLLM(ensuredMessage=inputMsg)

        allContent = "\n".join(m.content for m in result)
        occurrences = allContent.count(self._MEM_CONTENT)
        assert (
            occurrences == 1
        ), f"shared permanent memory should be injected exactly once, got {occurrences}:\n{allContent}"
