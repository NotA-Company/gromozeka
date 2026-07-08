"""Tests for the ``cache.chatUserMetadataLock()`` contract of :meth:`BaseBotHandler.setUserMetadata`.

Covers behaviour area (F): the ``isUpdate=True`` read-merge-write path must acquire
``cache.chatUserMetadataLock()`` exactly once around its read-merge-write, while the
full-replace path must not. Removing that wrapper reintroduces a lost-update race, and
these tests fail if the wrapper is dropped.

:meth:`BaseBotHandler.setUserMetadata` lives on :class:`BaseBotHandler`, which is
abstract / mixin-bound and not instantiated directly. It is exercised here through its
concrete subclass :class:`UserDataHandler`, constructed against a real in-memory database
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
from unittest.mock import AsyncMock, Mock

import pytest

from internal.bot.common.handlers.base import BaseBotHandler
from internal.bot.common.handlers.user_data import UserDataHandler
from internal.bot.models import (
    BotProvider,
    ChatSettingsDict,
    ChatSettingsKey,
    ChatSettingsValue,
    UserMetadataDict,
)
from internal.database import Database
from internal.database.repositories.user_memories import UserMemoryDict
from internal.services.cache import CacheService
from lib.ai import ModelMessage

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

    ``UserDataHandler.__init__`` reads ``get("user-memory", {})`` to cache the
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


async def _makeHandler(testDatabase: Database) -> UserDataHandler:
    """Construct a :class:`UserDataHandler` wired to a real in-memory database.

    Args:
        testDatabase: Fresh in-memory :class:`Database`` (``testDatabase``
            fixture).

    Returns:
        A :class:`UserDataHandler` whose ``db`` is *testDatabase*, used as the
        host for the inherited ``setUserMetadata`` helper.
    """
    CacheService._instance = None
    cache = CacheService.getInstance()
    await cache.injectDatabase(testDatabase)

    handler = UserDataHandler(
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
# User-memories v1 (Phase 3a) — _buildMemoriesBlock / _formatMemoriesBlock
# ---------------------------------------------------------------------------


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
            "type": memType,
            "content": content,
            "tags": tags or [],
            "permanent": permanent,
            "source": "refinement",
            "embedding_model": None,
            "embedding_dimensions": None,
            "created_at": _TS,
            "updated_at": updated_at,
        },
    )


def _memorySettings(
    *,
    injectionEnabled: bool = False,
    retrievalMode: str = "latest",
    embeddingsEnabled: bool = False,
    embeddingModel: str = "test/embed",
) -> ChatSettingsDict:
    """Build a chat-settings dict carrying the user-memory settings.

    Args:
        injectionEnabled: Value for ``MEMORY_INJECTION_ENABLED``.
        retrievalMode: Value for ``MEMORY_RETRIEVAL_MODE``.
        embeddingsEnabled: Value for ``EMBEDDINGS_ENABLED`` (gates relevant-mode embed).
        embeddingModel: Value for ``EMBEDDING_MODEL``.

    Returns:
        A :class:`ChatSettingsDict` with the four user-memory settings.
    """
    return {
        ChatSettingsKey.MEMORY_INJECTION_ENABLED: ChatSettingsValue("true" if injectionEnabled else "false"),
        ChatSettingsKey.MEMORY_RETRIEVAL_MODE: ChatSettingsValue(retrievalMode),
        ChatSettingsKey.EMBEDDINGS_ENABLED: ChatSettingsValue("true" if embeddingsEnabled else "false"),
        ChatSettingsKey.EMBEDDING_MODEL: ChatSettingsValue(embeddingModel),
    }


async def _makeMemoriesHandler(testDatabase: Database) -> UserDataHandler:
    """Construct a :class:`UserDataHandler` with ``db.userMemories`` mocked.

    Variant of :func:`_makeHandler` for the ``_buildMemoriesBlock`` tests: the
    handler is wired to a real in-memory database (for construction), then
    ``db.userMemories`` is swapped for a ``Mock`` whose repository methods are
    ``AsyncMock`` instances, so each test can script the permanent/ephemeral/search
    return values without seeding the DB.

    Args:
        testDatabase: Fresh in-memory :class:`Database` fixture.

    Returns:
        A :class:`UserDataHandler` whose ``self.db.userMemories`` is a ``Mock``
        with ``getPermanentMemories`` / ``getLatestMemories`` / ``searchMemories``
        set to fresh ``AsyncMock`` instances.
    """
    handler = await _makeHandler(testDatabase)
    mockUserMemories = Mock()
    mockUserMemories.getPermanentMemories = AsyncMock(return_value=[])
    mockUserMemories.getLatestMemories = AsyncMock(return_value=[])
    mockUserMemories.searchMemories = AsyncMock(return_value=[])
    handler.db.userMemories = mockUserMemories  # type: ignore[assignment]
    return handler


class TestBuildMemoriesBlock:
    """Phase-3a coverage for :meth:`BaseBotHandler._buildMemoriesBlock`.

    Pins the decision logic of the memories-block builder (plan §9.1 / §14.3):
    returns ``None`` when injection is disabled; resolves permanent + ephemeral
    in ``latest`` mode; switches to semantic ``searchMemories`` in ``relevant``
    mode when embeddings are on; falls back to latest on any embed/search
    failure; renders only the ``Recent:`` section when permanent is empty.
    """

    async def test_returnsNone_whenInjectionDisabled(self, testDatabase: Database) -> None:
        """``MEMORY_INJECTION_ENABLED=false`` short-circuits to ``None``.

        No DB method is awaited (the early return fires before the first
        ``userMemories`` call).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeMemoriesHandler(testDatabase)
        settings = _memorySettings(injectionEnabled=False)

        block = await handler._buildMemoriesBlock(
            _CHAT_ID,
            _USER_ID,
            _THREAD_ID,
            currentUserMessageText="hello",
            chatSettings=settings,
        )

        assert block is None
        handler.db.userMemories.getPermanentMemories.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_latestMode_returnsPermanentAndEphemeral(self, testDatabase: Database) -> None:
        """``mode=latest`` pulls permanent via ``getPermanentMemories`` + ephemeral via ``getLatestMemories``.

        Asserts both DB accessors are called with the right scoping and the
        rendered block contains both sections with the ``[type] content`` lines.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeMemoriesHandler(testDatabase)
        handler.db.userMemories.getPermanentMemories = AsyncMock(  # type: ignore[attr-defined]
            return_value=[_memoryDict(content="lives in Berlin", memType="fact", permanent=True, tags=["geo"])]
        )
        handler.db.userMemories.getLatestMemories = AsyncMock(  # type: ignore[attr-defined]
            return_value=[_memoryDict(content="asked about trains", memType="event")]
        )
        settings = _memorySettings(injectionEnabled=True, retrievalMode="latest")

        block = await handler._buildMemoriesBlock(
            _CHAT_ID,
            _USER_ID,
            _THREAD_ID,
            currentUserMessageText="hello",
            chatSettings=settings,
        )

        assert block is not None
        assert "<user-memories>" in block
        assert "</user-memories>" in block
        assert "Permanent:" in block
        assert "[fact] lives in Berlin #geo" in block
        assert "Recent:" in block
        assert "[event] asked about trains" in block
        # searchMemories must NOT be called in latest mode.
        handler.db.userMemories.searchMemories.assert_not_awaited()  # type: ignore[attr-defined]
        handler.db.userMemories.getPermanentMemories.assert_awaited_once()  # type: ignore[attr-defined]
        handler.db.userMemories.getLatestMemories.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_relevantMode_usesSearchMemories_whenEmbedSucceeds(self, testDatabase: Database) -> None:
        """``mode=relevant`` + ``EMBEDDINGS_ENABLED`` embeds the query + calls ``searchMemories``.

        ``_safeEmbedQuery`` is stubbed to return non-None bytes so the semantic
        path runs; ``getLatestMemories`` must NOT be called (search returned a
        non-empty list).

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeMemoriesHandler(testDatabase)
        handler.db.userMemories.getPermanentMemories = AsyncMock(return_value=[])  # type: ignore[attr-defined]
        handler.db.userMemories.searchMemories = AsyncMock(  # type: ignore[attr-defined]
            return_value=[_memoryDict(content="relevant hit", memType="fact")]
        )
        handler._safeEmbedQuery = AsyncMock(return_value=b"\x00\x00\x80\x3f")  # type: ignore[method-assign]
        settings = _memorySettings(injectionEnabled=True, retrievalMode="relevant", embeddingsEnabled=True)

        block = await handler._buildMemoriesBlock(
            _CHAT_ID,
            _USER_ID,
            _THREAD_ID,
            currentUserMessageText="what about trains",
            chatSettings=settings,
        )

        assert block is not None
        assert "[fact] relevant hit" in block
        handler._safeEmbedQuery.assert_awaited_once()  # type: ignore[attr-defined]
        handler.db.userMemories.searchMemories.assert_awaited_once()  # type: ignore[attr-defined]
        # searchMemories returned non-empty → getLatestMemories is the fallback
        # path and must NOT fire.
        handler.db.userMemories.getLatestMemories.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_returnsNone_whenBothPermanentAndEphemeralEmpty(self, testDatabase: Database) -> None:
        """Both sections empty → ``None`` (plan §9.1: "genuinely nothing to inject").

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeMemoriesHandler(testDatabase)
        # Both accessors already default to [] in _makeMemoriesHandler.
        settings = _memorySettings(injectionEnabled=True, retrievalMode="latest")

        block = await handler._buildMemoriesBlock(
            _CHAT_ID,
            _USER_ID,
            _THREAD_ID,
            currentUserMessageText="hello",
            chatSettings=settings,
        )

        assert block is None

    async def test_permanentEmpty_rendersRecentOnly(self, testDatabase: Database) -> None:
        """Permanent empty + ephemeral present → block with ONLY the ``Recent:`` section.

        This is the permanent-empty gap fix (plan §9.1): a brand-new user
        without a first bio still sees their ephemeral memories. Asserts the
        ``Permanent:`` header is absent so no empty section header renders.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeMemoriesHandler(testDatabase)
        handler.db.userMemories.getLatestMemories = AsyncMock(  # type: ignore[attr-defined]
            return_value=[_memoryDict(content="asked about trains", memType="event")]
        )
        settings = _memorySettings(injectionEnabled=True, retrievalMode="latest")

        block = await handler._buildMemoriesBlock(
            _CHAT_ID,
            _USER_ID,
            _THREAD_ID,
            currentUserMessageText="hello",
            chatSettings=settings,
        )

        assert block is not None
        assert "Permanent:" not in block
        assert "Recent:" in block
        assert "[event] asked about trains" in block

    async def test_relevantMode_fallsBackToLatest_onEmbedFailure(self, testDatabase: Database) -> None:
        """``mode=relevant`` with a failed embed (returns ``None``) falls back to latest.

        Pins the never-crash contract: a transient embedding outage (missing
        model, API error) downgrades to ``getLatestMemories`` rather than
        raising or returning an empty block.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeMemoriesHandler(testDatabase)
        handler.db.userMemories.getPermanentMemories = AsyncMock(return_value=[])  # type: ignore[attr-defined]
        handler.db.userMemories.getLatestMemories = AsyncMock(  # type: ignore[attr-defined]
            return_value=[_memoryDict(content="fallback latest", memType="event")]
        )
        handler._safeEmbedQuery = AsyncMock(return_value=None)  # type: ignore[method-assign]
        settings = _memorySettings(injectionEnabled=True, retrievalMode="relevant", embeddingsEnabled=True)

        block = await handler._buildMemoriesBlock(
            _CHAT_ID,
            _USER_ID,
            _THREAD_ID,
            currentUserMessageText="hello",
            chatSettings=settings,
        )

        assert block is not None
        assert "[event] fallback latest" in block
        handler._safeEmbedQuery.assert_awaited_once()  # type: ignore[attr-defined]
        # Embed failed → searchMemories never called, getLatestMemories fired.
        handler.db.userMemories.searchMemories.assert_not_awaited()  # type: ignore[attr-defined]
        handler.db.userMemories.getLatestMemories.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_relevantMode_fallsBackToLatest_whenEmbeddingsDisabled(self, testDatabase: Database) -> None:
        """``mode=relevant`` + ``EMBEDDINGS_ENABLED=false`` skips the embed call entirely.

        The chat-history ``EMBEDDINGS_ENABLED`` setting owns the embedding-API
        wiring; when it's off, no embed is attempted and latest mode runs.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeMemoriesHandler(testDatabase)
        handler.db.userMemories.getPermanentMemories = AsyncMock(return_value=[])  # type: ignore[attr-defined]
        handler.db.userMemories.getLatestMemories = AsyncMock(  # type: ignore[attr-defined]
            return_value=[_memoryDict(content="latest because embeddings off", memType="event")]
        )
        handler._safeEmbedQuery = AsyncMock(return_value=b"should-not-be-used")  # type: ignore[method-assign]
        settings = _memorySettings(injectionEnabled=True, retrievalMode="relevant", embeddingsEnabled=False)

        block = await handler._buildMemoriesBlock(
            _CHAT_ID,
            _USER_ID,
            _THREAD_ID,
            currentUserMessageText="hello",
            chatSettings=settings,
        )

        assert block is not None
        assert "[event] latest because embeddings off" in block
        handler._safeEmbedQuery.assert_not_awaited()  # type: ignore[attr-defined]
        handler.db.userMemories.searchMemories.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_dbErrorOnGetPermanentMemories_returnsNoneAndDoesNotRaise(self, testDatabase: Database) -> None:
        """A transient DB error from ``getPermanentMemories`` must NOT crash the turn.

        Pins the never-crash contract (Fix 1): memory injection is best-effort,
        so a live DB call raising (e.g. "database is locked", stale connection)
        must be caught by the outer ``try/except Exception`` safety net, logged,
        and downgraded to ``None`` rather than propagating and breaking the
        entire message turn. Before the fix, ``getPermanentMemories`` and
        ``getLatestMemories`` were unwrapped live DB calls.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeMemoriesHandler(testDatabase)
        handler.db.userMemories.getPermanentMemories = AsyncMock(  # type: ignore[attr-defined]
            side_effect=RuntimeError("db locked")
        )
        settings = _memorySettings(injectionEnabled=True, retrievalMode="latest")

        block = await handler._buildMemoriesBlock(
            _CHAT_ID,
            _USER_ID,
            _THREAD_ID,
            currentUserMessageText="hello",
            chatSettings=settings,
        )

        assert block is None
        handler.db.userMemories.getPermanentMemories.assert_awaited_once()  # type: ignore[attr-defined]
        # The crash happens at getPermanentMemories, so the fallback accessor
        # is never reached.
        handler.db.userMemories.getLatestMemories.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_dbErrorOnGetLatestMemories_returnsNoneAndDoesNotRaise(self, testDatabase: Database) -> None:
        """A transient DB error from ``getLatestMemories`` must NOT crash the turn.

        Companion to :meth:`test_dbErrorOnGetPermanentMemories_returnsNoneAndDoesNotRaise`:
        covers the second unwrapped live call. The permanent accessor
        succeeds, then the latest accessor raises — the outer safety net must
        still catch it and return ``None``.

        Args:
            testDatabase: Fresh in-memory database fixture.
        """
        handler = await _makeMemoriesHandler(testDatabase)
        handler.db.userMemories.getPermanentMemories = AsyncMock(return_value=[])  # type: ignore[attr-defined]
        handler.db.userMemories.getLatestMemories = AsyncMock(  # type: ignore[attr-defined]
            side_effect=RuntimeError("database is locked")
        )
        settings = _memorySettings(injectionEnabled=True, retrievalMode="latest")

        block = await handler._buildMemoriesBlock(
            _CHAT_ID,
            _USER_ID,
            _THREAD_ID,
            currentUserMessageText="hello",
            chatSettings=settings,
        )

        assert block is None
        handler.db.userMemories.getPermanentMemories.assert_awaited_once()  # type: ignore[attr-defined]
        handler.db.userMemories.getLatestMemories.assert_awaited_once()  # type: ignore[attr-defined]


class TestFormatMemoriesBlock:
    """Direct tests on :meth:`BaseBotHandler._formatMemoriesBlock` (staticmethod).

    Locks the render contract independently of the DB / settings: header
    omission for empty sections, tag formatting, and permanent-section sort
    order (by ``type`` then ``updated_at``).
    """

    def test_bothEmpty_returnsNone(self) -> None:
        """Both lists empty → ``None``."""
        assert BaseBotHandler._formatMemoriesBlock([], []) is None

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

        block = BaseBotHandler._formatMemoriesBlock(permanent, [])

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

        block = BaseBotHandler._formatMemoriesBlock(permanent, ephemeral)

        assert block is not None
        assert "[fact] lives in Berlin #geo #europe" in block
        assert "[event] no tags here\n" in block + "\n"


class TestInjectMemoriesBlock:
    """Pins :meth:`BaseBotHandler._injectMemoriesBlock` mutation contract."""

    def test_appendsBlockToSystemMessageContent(self) -> None:
        """A non-None block is appended to ``messages[0].content`` after a blank line."""
        handler = _injectOnlyHandler()
        messages = [ModelMessage(role="system", content="BASE")]

        handler._injectMemoriesBlock(messages, "<user-memories>x</user-memories>")

        assert messages[0].content == "BASE\n\n<user-memories>x</user-memories>"

    def test_noopOnNoneBlock(self) -> None:
        """``None`` block leaves ``messages[0].content`` untouched."""
        handler = _injectOnlyHandler()
        messages = [ModelMessage(role="system", content="BASE")]

        handler._injectMemoriesBlock(messages, None)

        assert messages[0].content == "BASE"

    def test_noopOnEmptyMessages(self) -> None:
        """Empty ``messages`` list is a no-op (no IndexError)."""
        handler = _injectOnlyHandler()
        handler._injectMemoriesBlock([], "<user-memories>x</user-memories>")  # must not raise


def _injectOnlyHandler() -> BaseBotHandler:
    """Build a bare :class:`BaseBotHandler` instance for pure-method tests.

    ``_injectMemoriesBlock`` touches no instance state, so a
    ``object.__new__``-style instance is enough. We use ``UserDataHandler``'s
    construction path indirectly is overkill; instead we bypass ``__init__``
    via ``BaseBotHandler.__new__`` since the method is non-stateful.

    Returns:
        A :class:`BaseBotHandler` instance with ``__init__`` skipped.
    """
    return BaseBotHandler.__new__(BaseBotHandler)
