"""Comprehensive tests for :class:`ChatSearchHandler`.

Covers the three layers of the handler in isolation:

* ``_parseSearchArgs`` — the ``key: value`` argument parser used by
  ``/search``.
* ``searchCommand`` — the ``/search`` user command (rate-limit → DB
  filter → client-side keyword filter → raw-formatted reply).
* ``_dtCronJob`` — the embedding-backfill CRON_JOB (construction-time
  gate via ``[search-history].enabled``, ``REGENERATE_EMBEDDINGS`` chat
  discovery, model resolution, batch embedding, per-message error
  handling).

All tests are wired through the project's :mod:`pytest` configuration
(``asyncio_mode = "auto"``) and use the autouse singleton-reset
fixtures from ``tests/conftest.py``. The handler's database, LLM
service, and message-sending methods are stubbed at the instance
level so the tests never touch a real bot, LLM provider, or database.
"""

import datetime
from typing import Any, Dict, List, Optional, Tuple, cast
from unittest.mock import AsyncMock, Mock

import pytest

from internal.bot.common.handlers.chat_search import (
    BACKFILL_DEFAULT_BATCH_SIZE,
    SEARCH_DEFAULT_MAX_RESULTS,
    ChatSearchHandler,
)
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
from internal.models import MessageId
from internal.services.queue_service.types import DelayedTask, DelayedTaskFunction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


HandlerMocks = Dict[str, Any]


def _makeChatSettings(
    *,
    embeddingModel: str = "",
    allowTools: bool = True,
    embeddingsEnabled: bool = True,
) -> ChatSettingsDict:
    """Build a chat-settings dict pre-populated with every key the handler reads.

    Args:
        embeddingModel: Value for ``EMBEDDING_MODEL`` (default empty string;
            the handler treats empty as "no embedding model configured"
            and skips the semantic-search path). Tests that exercise
            semantic search override this with a non-empty model name
            and stub the LLM manager to return a model mock for it.
        allowTools: Value for ``ALLOW_TOOLS_COMMANDS`` (default ``True``).
        embeddingsEnabled: Value for ``EMBEDDINGS_ENABLED`` (default ``True``).

    Returns:
        Mapping of every relevant :class:`ChatSettingsKey` to a
        :class:`ChatSettingsValue` carrying a deterministic test value.
    """
    return {
        ChatSettingsKey.REGENERATE_EMBEDDINGS: ChatSettingsValue("true"),
        ChatSettingsKey.EMBEDDING_MODEL: ChatSettingsValue(embeddingModel),
        ChatSettingsKey.LLM_RATELIMITER: ChatSettingsValue(""),
        ChatSettingsKey.ALLOW_TOOLS_COMMANDS: ChatSettingsValue("true" if allowTools else "false"),
        ChatSettingsKey.EMBEDDINGS_ENABLED: ChatSettingsValue("true" if embeddingsEnabled else "false"),
    }


def _makeEnsuredMessage(
    *,
    chatId: int = 100,
    messageId: int = 42,
    userId: int = 7,
    senderName: str = "Alice",
) -> EnsuredMessage:
    """Build a minimal :class:`EnsuredMessage` suitable for handler tests.

    Args:
        chatId: Recipient chat id (default 100).
        messageId: Originating message id (Telegram-flavoured int, default 42).
        userId: Sender user id (default 7).
        senderName: ``MessageSender.name`` value (default ``"Alice"``).

    Returns:
        Fully constructed :class:`EnsuredMessage`.
    """
    return EnsuredMessage(
        sender=MessageSender(id=userId, name=senderName, username=f"@user{userId}"),
        recipient=MessageRecipient(id=chatId, chatType=ChatType.PRIVATE),
        messageId=messageId,
        date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText="/search",
    )


def _makeConfigManager(
    *,
    maxResults: int = SEARCH_DEFAULT_MAX_RESULTS,
    defaultDays: int = 30,
    enabled: bool = True,
) -> Mock:
    """Build a stand-in ``ConfigManager`` for the handler constructor.

    Args:
        maxResults: ``[search-history.defaults].max-results`` value.
        defaultDays: ``[search-history.defaults].default-days`` value.
        enabled: ``[search-history].enabled`` value (default ``True``).
            Tests that exercise the server-level kill-switch on the
            backfill CRON_JOB flip this to ``False``.

    Returns:
        ``Mock`` exposing ``getBotConfig()`` and ``getSearchHistoryConfig()``
        with deterministic return values.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test", "owners": []})
    cm.getSearchHistoryConfig = Mock(
        return_value={
            "enabled": enabled,
            "defaults": {"max-results": maxResults, "default-days": defaultDays},
        }
    )
    return cm


def _makeDatabase() -> Mock:
    """Build a ``Database`` stub with a ``chatSearch`` repository placeholder.

    Returns:
        ``Mock`` whose ``chatSearch`` attribute is itself a ``Mock``.
        Tests add the specific repository methods they need.
    """
    db = Mock()
    db.chatSearch = Mock()
    return db


def _makeHandler(
    *,
    configManager: Optional[Mock] = None,
    chatSettings: Optional[ChatSettingsDict] = None,
) -> Tuple[ChatSearchHandler, HandlerMocks]:
    """Construct a :class:`ChatSearchHandler` with stubs ready for tests.

    The handler's ``llmService`` is the real ``LLMService`` singleton
    (the autouse ``resetLlmServiceSingleton`` fixture has already reset
    it before the test). Only the ``rateLimit`` method is overridden on
    the instance, since it's the only one the command path uses.

    ``getChatSettings`` / ``sendMessage`` are stubbed at the instance
    level to avoid touching the cache or bot during tests.

    Args:
        configManager: Optional preconfigured config-manager stub.
            Defaults to :func:`_makeConfigManager`.
        chatSettings: Optional override for the chat-settings dict
            returned by ``getChatSettings``. Defaults to
            :func:`_makeChatSettings`.

    Returns:
        Tuple ``(handler, mocks)`` where ``mocks`` is a dict of the
        injected mocks for direct, type-permissive access from tests.
    """
    cm = configManager if configManager is not None else _makeConfigManager()
    db = _makeDatabase()
    handler = ChatSearchHandler(
        configManager=cm,
        database=db,
        botProvider=BotProvider.TELEGRAM,
    )

    # Override the singleton LLMService methods we exercise.
    rateLimitMock = AsyncMock(return_value=None)
    cast(Any, handler).llmService.rateLimit = rateLimitMock

    # Stub chat-settings retrieval and message sending.
    cs = chatSettings if chatSettings is not None else _makeChatSettings()
    getChatSettingsMock = AsyncMock(return_value=cs)
    cast(Any, handler).getChatSettings = getChatSettingsMock

    sendMessageMock = AsyncMock(return_value=[])
    cast(Any, handler).sendMessage = sendMessageMock

    mocks: HandlerMocks = {
        "rateLimit": rateLimitMock,
        "getChatSettings": getChatSettingsMock,
        "sendMessage": sendMessageMock,
        "db": db,
        "configManager": cm,
    }
    return handler, mocks


def _callSearch(handler: ChatSearchHandler, ensuredMessage: EnsuredMessage, args: str) -> Any:
    """Invoke ``searchCommand`` past pyright's unbound-signature view.

    ``commandHandlerV2`` returns the wrapped function unchanged, so
    calling the bound method through ``cast(Any, ...)`` is safe.

    Args:
        handler: Handler under test.
        ensuredMessage: Originating user message.
        args: Raw arguments string after ``/search``.

    Returns:
        Whatever the underlying coroutine returns (always ``None``).
    """
    return cast(Any, handler).searchCommand(
        ensuredMessage,
        "search",
        args,
        updateObj=Mock(),
        typingManager=None,
    )


def _sampleRow(
    *,
    messageId: int = 1,
    text: str = "meeting notes",
    username: str = "alice",
    daysAgo: int = 0,
) -> Dict[str, Any]:
    """Build a ``ChatMessageDict``-shaped row for stubbing ``searchChatMessages``.

    Args:
        messageId: ``message_id`` value (default 1).
        text: ``message_text`` value (default ``"meeting notes"``).
        username: ``username`` value (default ``"alice"``).
        daysAgo: How many days before ``2026-05-05 12:00 UTC`` the
            message should be dated (default 0).

    Returns:
        A dict matching the shape the handler reads after the DB call.
    """
    base = datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)
    return {
        "chat_id": 100,
        "message_id": messageId,
        "message_text": text,
        "date": base - datetime.timedelta(days=daysAgo),
        "user_id": 7,
        "username": username,
        "full_name": username.capitalize(),
        "message_category": MessageCategory.USER,
        "score": 0.0,
    }


# ---------------------------------------------------------------------------
# 1. Parser tests
# ---------------------------------------------------------------------------


class TestParseSearchArgs:
    """Tests for :meth:`ChatSearchHandler._parseSearchArgs`."""

    _EMPTY: Dict[str, Optional[str]] = {
        "keywords": None,
        "user": None,
        "days": None,
        "category": None,
        "thread": None,
        "chat": None,
    }

    @pytest.mark.parametrize(
        ("argsInput", "expected"),
        [
            ("", {**_EMPTY}),
            ("hello", {**_EMPTY, "keywords": "hello"}),
            ("hello world", {**_EMPTY, "keywords": "hello world"}),
            ("keywords:meeting", {**_EMPTY, "keywords": "meeting"}),
            ("keywords: meeting", {**_EMPTY, "keywords": "meeting"}),
            ("keywords: hello world", {**_EMPTY, "keywords": "hello world"}),
            ("days: 7", {**_EMPTY, "days": "7"}),
            ("user: @alice", {**_EMPTY, "user": "@alice"}),
            ("category: bot", {**_EMPTY, "category": "bot"}),
            ("thread: 12345", {**_EMPTY, "thread": "12345"}),
            ("days: 7 keywords: meeting", {**_EMPTY, "days": "7", "keywords": "meeting"}),
            ("hello keywords: meeting", {**_EMPTY, "keywords": "hello meeting"}),
            (
                "keywords: hello world days: 7 user: @alice category: bot",
                {
                    "keywords": "hello world",
                    "user": "@alice",
                    "days": "7",
                    "category": "bot",
                    "thread": None,
                    "chat": None,
                },
            ),
            ("unknown: value", {**_EMPTY, "keywords": "unknown: value"}),
            ("days: abc", {**_EMPTY, "days": "abc"}),
            ("keywords: hello days: 7 days: 5", {**_EMPTY, "keywords": "hello", "days": "7"}),
        ],
    )
    def test_parseSearchArgs(self, argsInput: str, expected: Dict[str, Optional[str]]) -> None:
        """``_parseSearchArgs`` should produce the expected dict for the given input.

        Args:
            argsInput: Raw argument string to parse.
            expected: Expected parsed-result dict.
        """
        result = ChatSearchHandler._parseSearchArgs(argsInput)
        assert result == expected


# ---------------------------------------------------------------------------
# 2. Command handler tests
# ---------------------------------------------------------------------------


class TestSearchCommand:
    """Tests for :meth:`ChatSearchHandler.searchCommand`."""

    async def test_search_empty_keywords_shows_help(self) -> None:
        """``/search`` (no args) sends the help text and skips the DB call.

        ``keywords:`` is no longer required — the help text is the
        user-facing fallback when the user invokes ``/search`` without
        providing *any* of ``keywords``/``user``/``days``/``thread``.
        The reply must be sent as a plain command reply (not a summary
        or an error), and no DB or rate-limit work is done.
        """
        handler, mocks = _makeHandler()
        em = _makeEnsuredMessage()

        await _callSearch(handler, em, "")

        mocks["sendMessage"].assert_awaited_once()
        sentKwargs = mocks["sendMessage"].call_args.kwargs
        sentText: str = sentKwargs.get("messageText", "")
        assert "Семантический поиск" in sentText
        assert "хотя бы один из" in sentText
        assert sentKwargs.get("messageCategory") == MessageCategory.BOT_COMMAND_REPLY
        # No DB or LLM work when the request has no filter at all.
        mocks["db"].chatSearch.searchChatMessages.assert_not_called()
        mocks["rateLimit"].assert_not_called()

    async def test_search_no_results(self) -> None:
        """``/search keywords: meeting`` with empty DB results sends a no-results reply.

        The handler must short-circuit on the empty result set so the
        user sees a clean "no results" message and the formatter is
        not invoked on an empty list.
        """
        handler, mocks = _makeHandler()
        mocks["db"].chatSearch.searchChatMessages = AsyncMock(return_value=[])
        em = _makeEnsuredMessage()

        await _callSearch(handler, em, "keywords: meeting")

        mocks["sendMessage"].assert_awaited_once()
        sentText: str = mocks["sendMessage"].call_args.kwargs.get("messageText", "")
        assert "Сообщения по вашему запросу не найдены" in sentText

    async def test_search_with_results(self) -> None:
        """``/search keywords: meeting`` returns raw formatted results when matches exist.

        The reply text is built as ``"Найдено N сообщений:\\n\\n<raw lines>"``;
        the formatted result lines (one per matching message with date,
        username, and message text) must be embedded verbatim and the
        reply is sent as a plain command reply (no LLM is involved).
        """
        handler, mocks = _makeHandler()
        rows = [_sampleRow(text="meeting notes")]
        mocks["db"].chatSearch.searchChatMessages = AsyncMock(return_value=rows)
        em = _makeEnsuredMessage()

        await _callSearch(handler, em, "keywords: meeting")

        mocks["sendMessage"].assert_awaited_once()
        sentKwargs = mocks["sendMessage"].call_args.kwargs
        sentText: str = sentKwargs.get("messageText", "")
        assert "Найдено 1 сообщений" in sentText
        # The raw result line includes the formatted date, username,
        # and message body.
        assert "@alice" in sentText
        assert "meeting notes" in sentText
        # The reply is a plain command reply — no LLM summary path.
        assert sentKwargs.get("messageCategory") == MessageCategory.BOT_COMMAND_REPLY
        # No "Сводка" prefix because the handler no longer summarises.
        assert "Сводка" not in sentText

    async def test_search_rate_limit_called(self) -> None:
        """``/search`` calls ``llmService.rateLimit`` before the DB call.

        Rate-limiting runs **before** any (potentially expensive) DB
        query, so an abusive ``/search`` is gated up-front. The test
        enforces the order via a ``side_effect``-appended list and
        additionally checks the positional ``chatId`` argument.
        """
        handler, mocks = _makeHandler()
        callOrder: List[str] = []
        rateLimitMock = AsyncMock(side_effect=lambda *a, **k: callOrder.append("rateLimit"))
        searchMock = AsyncMock(side_effect=lambda *a, **k: (callOrder.append("search"), [])[1])
        cast(Any, handler).llmService.rateLimit = rateLimitMock
        mocks["db"].chatSearch.searchChatMessages = searchMock
        em = _makeEnsuredMessage()

        await _callSearch(handler, em, "keywords: meeting")

        # rateLimit is called first, then search.
        assert callOrder == ["rateLimit", "search"]
        # rateLimit is invoked with the chatId as the first positional arg.
        assert rateLimitMock.call_args.args[0] == em.recipient.id

    async def test_search_days_validation_error(self) -> None:
        """``/search days: abc`` reports a validation error and skips the DB call.

        Validation runs before rate-limiting so a malformed ``days``
        value does not consume a rate-limit token. The error is sent as
        a plain command reply.
        """
        handler, mocks = _makeHandler()
        em = _makeEnsuredMessage()

        await _callSearch(handler, em, "days: abc keywords: meeting")

        mocks["db"].chatSearch.searchChatMessages.assert_not_called()
        mocks["rateLimit"].assert_not_called()
        mocks["sendMessage"].assert_awaited_once()
        sentText: str = mocks["sendMessage"].call_args.kwargs.get("messageText", "")
        assert "должен быть числом" in sentText

    async def test_search_keyword_matches_outside_max_results_window(self) -> None:
        """``/search`` passes ``limit=_maxResults`` to the DB.

        The DB handles keyword matching (via vector search / semantic
        ranking), so the handler always passes ``limit=self._maxResults``
        rather than requesting the full result set and filtering
        client-side.
        """
        handler, mocks = _makeHandler()  # _maxResults defaults to 10
        # DB returns only the 2 matches — vector search handles ranking.
        matches = [
            _sampleRow(messageId=20, text="meeting notes day 1", daysAgo=6),
            _sampleRow(messageId=21, text="meeting recap day 2", daysAgo=7),
        ]
        mocks["db"].chatSearch.searchChatMessages = AsyncMock(return_value=matches)
        em = _makeEnsuredMessage()

        await _callSearch(handler, em, "keywords: meeting")

        # The DB call always uses ``limit=self._maxResults``.
        callKwargs = mocks["db"].chatSearch.searchChatMessages.call_args.kwargs
        assert callKwargs["limit"] == 10

        # Reply shows the 2 keyword matches.
        mocks["sendMessage"].assert_awaited_once()
        sentKwargs = mocks["sendMessage"].call_args.kwargs
        sentText: str = sentKwargs.get("messageText", "")
        assert "Найдено 2 сообщений" in sentText
        assert "не найдены" not in sentText
        assert sentKwargs.get("messageCategory") == MessageCategory.BOT_COMMAND_REPLY

    async def test_search_truncates_to_max_results_after_keyword_filter(self) -> None:
        """``/search`` caps the results at ``_maxResults``.

        The DB returns up to ``_maxResults`` rows. The handler also
        truncates to ``_maxResults`` as a safety cap in case the DB
        returns more (e.g., when no embedding was generated).
        """
        handler, mocks = _makeHandler()  # _maxResults defaults to 10
        # 15 keyword matches — the handler should keep only 10.
        allMatches = [_sampleRow(messageId=i, text=f"meeting {i}", daysAgo=i) for i in range(15)]
        mocks["db"].chatSearch.searchChatMessages = AsyncMock(return_value=allMatches)
        em = _makeEnsuredMessage()

        await _callSearch(handler, em, "keywords: meeting")

        # The DB call uses ``limit=self._maxResults``.
        callKwargs = mocks["db"].chatSearch.searchChatMessages.call_args.kwargs
        assert callKwargs["limit"] == 10

        # The reply counts exactly 10 matches, not 15.
        sentText: str = mocks["sendMessage"].call_args.kwargs.get("messageText", "")
        assert "Найдено 10 сообщений" in sentText

    async def test_search_filter_only_uses_db_limit(self) -> None:
        """``/search days: 365`` (no keywords) passes ``limit=_maxResults`` to the DB.

        Regression: When the user searches without keywords (filter-only),
        the handler must pass ``limit=self._maxResults`` to
        ``searchChatMessages`` so the SQL query is bounded. The previous
        code passed ``limit=None`` for every path, which could return an
        unbounded result set for filter-only queries.
        """
        handler, mocks = _makeHandler()
        manyRows = [_sampleRow(messageId=i, text=f"meeting {i}", daysAgo=i) for i in range(50)]
        mocks["db"].chatSearch.searchChatMessages = AsyncMock(return_value=manyRows)
        em = _makeEnsuredMessage()

        await _callSearch(handler, em, "days: 365")

        # The DB call must have limit=_maxResults (bounded), not None.
        callKwargs = mocks["db"].chatSearch.searchChatMessages.call_args.kwargs
        assert callKwargs["limit"] == SEARCH_DEFAULT_MAX_RESULTS

        # Reply shows at most _maxResults results, not all 50.
        sentText: str = mocks["sendMessage"].call_args.kwargs.get("messageText", "")
        assert f"Найдено {SEARCH_DEFAULT_MAX_RESULTS} сообщений" in sentText

    @pytest.mark.parametrize(
        ("category", "expected"),
        [
            (
                "user",
                [
                    MessageCategory.USER,
                    MessageCategory.USER_COMMAND,
                    MessageCategory.USER_CONFIG_ANSWER,
                ],
            ),
            (
                "bot",
                [
                    MessageCategory.BOT,
                    MessageCategory.BOT_COMMAND_REPLY,
                    MessageCategory.BOT_SUMMARY,
                    MessageCategory.BOT_RESENDED,
                    MessageCategory.BOT_ERROR,
                ],
            ),
            (
                "system",
                [
                    MessageCategory.USER_SPAM,
                    MessageCategory.BOT_SPAM_NOTIFICATION,
                    MessageCategory.DELETED,
                    MessageCategory.UNSPECIFIED,
                ],
            ),
            ("channel", [MessageCategory.CHANNEL]),
        ],
    )
    def test_search_category_resolution(
        self,
        category: str,
        expected: List[MessageCategory],
    ) -> None:
        """``_resolveCategoryGroup`` maps user-facing aliases to ``MessageCategory`` lists.

        Args:
            category: User-facing category alias.
            expected: Expected resolved category list.
        """
        result = ChatSearchHandler._resolveCategoryGroup(category)
        assert result == expected

    @pytest.mark.parametrize("badValue", [None, "", "nonsense"])
    def test_search_category_resolution_unknown(self, badValue: Optional[str]) -> None:
        """``_resolveCategoryGroup`` returns ``None`` for unknown / missing values.

        The handler treats a ``None`` category filter as "do not filter by
        category", which is the right behaviour for unknown aliases so
        a typo doesn't silently drop every search result.

        Args:
            badValue: Value to pass to ``_resolveCategoryGroup``.
        """
        assert ChatSearchHandler._resolveCategoryGroup(badValue) is None

    def test_search_category_resolution_is_case_insensitive(self) -> None:
        """``_resolveCategoryGroup`` is case-insensitive on its input.

        ``"BOT"`` should resolve to the same category list as ``"bot"``.
        """
        assert ChatSearchHandler._resolveCategoryGroup("BOT") == ChatSearchHandler._resolveCategoryGroup("bot")

    @pytest.mark.parametrize(
        ("args", "shouldShowHelp"),
        [
            # No content filter at all — help text is shown.
            ("", True),
            ("chat: @othergroup", True),
            ("category: bot", True),
            # At least one of (keywords / user / days / thread) is set —
            # the request proceeds to the search path, not the help text.
            ("keywords: meeting", False),
            ("keywords: hello world", False),
            ("days: 7", False),
            ("user: @alice", False),
            ("thread: 12345", False),
            ("category: bot days: 7", False),
        ],
    )
    async def test_search_filter_validation(self, args: str, shouldShowHelp: bool) -> None:
        """The ``/search`` validation gate triggers help when no content filter is set.

        ``keywords:`` is no longer the only valid input — at least one
        of ``keywords``/``user``/``days``/``thread`` is required to
        proceed. ``category:`` and ``chat:`` alone do not count
        (they are a refinement and a routing arg respectively), so
        a request with only those must show the help text.

        Args:
            args: Raw argument string passed to ``/search``.
            shouldShowHelp: Expected dispatch outcome — ``True`` for
                help, ``False`` for proceeding to the search path.
        """
        handler, mocks = _makeHandler()
        # When the request proceeds, a (possibly empty) search result
        # is the path's terminal state. The DB is never queried when
        # the help text is shown.
        mocks["db"].chatSearch.searchChatMessages = AsyncMock(return_value=[])

        await _callSearch(handler, _makeEnsuredMessage(), args)

        mocks["sendMessage"].assert_awaited_once()
        sentText: str = mocks["sendMessage"].call_args.kwargs.get("messageText", "")
        if shouldShowHelp:
            assert "хотя бы один из" in sentText
            mocks["db"].chatSearch.searchChatMessages.assert_not_called()
        else:
            # Proceeding paths reach either the "no results" reply
            # or a formatted results reply — both are NOT the help
            # text, and both go through the DB.
            assert "хотя бы один из" not in sentText
            mocks["db"].chatSearch.searchChatMessages.assert_awaited_once()


class TestHasAnyFilter:
    """Tests for :meth:`ChatSearchHandler._hasAnyFilter` (static).

    The gate keeps a no-filter ``/search`` request from issuing an
    unbounded query against the chat. ``category`` and ``chat`` are
    explicitly excluded — they refine or route the query, they do
    not narrow the result set on their own.
    """

    @pytest.mark.parametrize(
        "parsed",
        [
            {},
            {"keywords": None, "user": None, "days": None, "thread": None},
            {"category": "bot"},
            {"chat": "@othergroup"},
            {"category": "bot", "chat": "@othergroup"},
        ],
    )
    def test_hasAnyFilter_false(self, parsed: Dict[str, Optional[str]]) -> None:
        """``_hasAnyFilter`` returns ``False`` when no content filter is set.

        Args:
            parsed: Parsed-args dict to test.
        """
        assert ChatSearchHandler._hasAnyFilter(parsed) is False

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("keywords", "meeting"),
            ("user", "@alice"),
            ("days", "7"),
            ("days", "abc"),  # malformed days still counts as a filter
            ("thread", "12345"),
        ],
    )
    def test_hasAnyFilter_true_for_each_content_key(self, key: str, value: str) -> None:
        """Any of ``keywords``/``user``/``days``/``thread`` set → ``True``.

        Args:
            key: Filter key to populate.
            value: Value to assign to the filter key.
        """
        parsed: Dict[str, Optional[str]] = {key: value}
        assert ChatSearchHandler._hasAnyFilter(parsed) is True

    def test_hasAnyFilter_true_when_multiple_keys_set(self) -> None:
        """Multiple content keys all set → still ``True`` (idempotent).

        Mirrors a realistic ``/search keywords: meeting days: 7 user: @alice``
        invocation: the gate only requires *one* filter, but having
        more must not flip the result back to ``False``.
        """
        parsed: Dict[str, Optional[str]] = {
            "keywords": "meeting",
            "user": "@alice",
            "days": "7",
            "thread": None,
            "category": "bot",
            "chat": "@othergroup",
        }
        assert ChatSearchHandler._hasAnyFilter(parsed) is True


class TestResolveTargetChatId:
    """Tests for :meth:`ChatSearchHandler._resolveTargetChatId` (async instance method).

    The method resolves a ``chat:`` argument to a chat id the sender
    is admin of. Only numeric ids are accepted — any other input
    (usernames, free-form text) is treated as unresolvable. The
    parse-failure and not-admin failure modes are intentionally
    conflated so the user-visible reply does not leak which one
    occurred.
    """

    async def test_resolveTargetChatId_none_arg_returns_none(self) -> None:
        """``None`` argument → ``None`` (no chat to resolve)."""
        handler, _mocks = _makeHandler()
        em = _makeEnsuredMessage()

        result = await handler._resolveTargetChatId(  # type: ignore[attr-defined]
            ensuredMessage=em,
            chatArg=None,
        )
        assert result is None

    async def test_resolveTargetChatId_empty_arg_returns_none(self) -> None:
        """Empty / whitespace-only argument → ``None``."""
        handler, _mocks = _makeHandler()
        em = _makeEnsuredMessage()

        for empty in ("", "   "):
            result = await handler._resolveTargetChatId(  # type: ignore[attr-defined]
                ensuredMessage=em,
                chatArg=empty,
            )
            assert result is None

    async def test_resolveTargetChatId_numeric_id_sender_is_admin(self) -> None:
        """Numeric id + sender is admin → returns the parsed int.

        The method parses the argument as an int and shortcuts
        straight to the admin gate.
        """
        handler, mocks = _makeHandler()
        em = _makeEnsuredMessage()
        # ``isAdmin`` returns ``True`` for the sender.
        cast(Any, handler).isAdmin = AsyncMock(return_value=True)  # type: ignore[method-assign]
        # ``chatInfo`` should not be touched at all on the numeric path.
        mocks["db"].chatInfo = Mock()

        result = await handler._resolveTargetChatId(  # type: ignore[attr-defined]
            ensuredMessage=em,
            chatArg="-1001234567890",
        )

        assert result == -1001234567890
        # The numeric path must not consult any chatInfo method.
        mocks["db"].chatInfo.getChatByUsername.assert_not_called()  # type: ignore[attr-defined]
        mocks["db"].chatInfo.getChatInfo.assert_not_called()  # type: ignore[attr-defined]

    async def test_resolveTargetChatId_username_arg_returns_none(self) -> None:
        """``@username`` argument → ``None`` (only numeric ids are accepted).

        ``_resolveTargetChatId`` no longer falls back to a username
        lookup; the chat-info repository has no
        ``getChatByUsername`` method anymore. Any non-numeric input
        is treated as unresolvable and ``None`` is returned.
        """
        handler, mocks = _makeHandler()
        em = _makeEnsuredMessage()
        cast(Any, handler).isAdmin = AsyncMock(return_value=True)  # type: ignore[method-assign]
        # The repository is wired defensively to prove the handler
        # never reaches it on a username input.
        mocks["db"].chatInfo = Mock()

        result = await handler._resolveTargetChatId(  # type: ignore[attr-defined]
            ensuredMessage=em,
            chatArg="@othergroup",
        )

        assert result is None
        mocks["db"].chatInfo.getChatByUsername.assert_not_called()  # type: ignore[attr-defined]

    async def test_resolveTargetChatId_garbage_arg_returns_none(self) -> None:
        """Free-form / unparsable argument → ``None`` (not a valid integer)."""
        handler, _mocks = _makeHandler()
        em = _makeEnsuredMessage()
        cast(Any, handler).isAdmin = AsyncMock(return_value=True)  # type: ignore[method-assign]

        for bad in ("not-a-number", "abc123", "--100", "12.34", "  "):
            result = await handler._resolveTargetChatId(  # type: ignore[attr-defined]
                ensuredMessage=em,
                chatArg=bad,
            )
            assert result is None

    async def test_resolveTargetChatId_not_admin_returns_none(self) -> None:
        """Resolved numeric id exists, sender is not admin → ``None`` (not authorised).

        The parse-failure and not-admin failure modes must be
        conflated so the reply does not leak which one occurred.
        """
        handler, _mocks = _makeHandler()
        em = _makeEnsuredMessage()
        cast(Any, handler).isAdmin = AsyncMock(return_value=False)  # type: ignore[method-assign]

        result = await handler._resolveTargetChatId(  # type: ignore[attr-defined]
            ensuredMessage=em,
            chatArg="-1009876543210",
        )

        assert result is None


# ---------------------------------------------------------------------------
# 2b. Semantic search wiring (Fix 9)
# ---------------------------------------------------------------------------


def _stubEmbeddingModel(handler: ChatSearchHandler, model: Mock) -> Mock:
    """Wire a mock embedding model into the handler's LLM service.

    Replaces ``handler.llmService.getLLMManager`` with a ``Mock`` that
    returns a mock manager whose ``getModel`` returns *model* for any
    name. Used by :class:`TestSemanticSearch` to control the
    `getModel` / `supportsEmbedding` / `generateEmbeddings` surface
    that the handler consults when ``EMBEDDING_MODEL`` is configured
    for the chat.

    Args:
        handler: Handler under test.
        model: Mock model instance (caller configures
            ``supportsEmbedding`` and ``generateEmbeddings`` as needed).

    Returns:
        The mock manager (returned for tests that want to assert on
        ``getModel`` call args).
    """
    mockManager = Mock()
    mockManager.getModel = Mock(return_value=model)
    cast(Any, handler).llmService.getLLMManager = Mock(return_value=mockManager)
    return mockManager


class TestSemanticSearch:
    """Tests for the semantic-search wiring in the ``/search`` command.

    The handler resolves the chat's ``EMBEDDING_MODEL`` setting, looks
    the model up in the LLM manager, and (when the model supports
    embeddings) generates a query vector for the keyword. The vector is
    then passed to ``chatSearch.searchChatMessages`` so the repository
    can do a semantic ranking pass on top of the SQL filter.

    These tests pin the contract down so a future refactor cannot
    silently drop the query-embedding step (which would break semantic
    search for every chat that has the feature enabled) or
    accidentally leak embedding failures into the user-visible reply.
    """

    async def test_semantic_search_generates_query_embedding(self) -> None:
        """``/search keywords: ...`` calls ``generateEmbeddings`` and forwards the vector.

        The handler must:
        1. Read the chat's ``EMBEDDING_MODEL`` setting and resolve it
           via ``llmService.getLLMManager().getModel(name)``.
        2. Skip embedding when ``model is None`` or
           ``model.supportsEmbedding`` is ``False`` (covered by the
           sibling tests).
        3. Call ``model.generateEmbeddings(keywords)`` and pass the
           returned vector to ``searchChatMessages`` as
           ``queryEmbedding``, plus the model name as ``modelName`` so
           the repository can load the matching stored vectors for
           cosine comparison.
        """
        handler, mocks = _makeHandler(
            chatSettings=_makeChatSettings(embeddingModel="text-embedding-3-small"),
        )
        mockModel = Mock()
        mockModel.supportsEmbedding = True
        mockModel.generateEmbeddings = AsyncMock(return_value=[0.1, 0.2, 0.3])
        mockManager = _stubEmbeddingModel(handler, mockModel)
        mocks["db"].chatSearch.searchChatMessages = AsyncMock(return_value=[])

        await _callSearch(handler, _makeEnsuredMessage(), "keywords: meeting")

        # The model name was resolved via the LLM manager.
        mockManager.getModel.assert_called_with("text-embedding-3-small")
        # The query embedding was generated from the raw keywords.
        mockModel.generateEmbeddings.assert_awaited_once()
        assert mockModel.generateEmbeddings.await_args.args[0] == "meeting"
        # The embedding vector + model name were forwarded to the repository.
        callKwargs = mocks["db"].chatSearch.searchChatMessages.call_args.kwargs
        assert callKwargs["queryEmbedding"] == [0.1, 0.2, 0.3]
        assert callKwargs["modelName"] == "text-embedding-3-small"

    async def test_semantic_search_falls_back_on_embedding_failure(self) -> None:
        """When ``generateEmbeddings`` raises, ``queryEmbedding`` falls back to ``None``.

        A flaky embedding API must not break ``/search`` — the
        handler logs the failure and falls back to filter-only mode
        (the same path used when no keywords are present or when the
        chat has no ``EMBEDDING_MODEL`` configured). The
        ``modelName`` is still forwarded to the repository so it can
        load any stored embeddings the chat has for ranking, but the
        ``queryEmbedding`` is ``None`` so no semantic comparison runs.
        """
        handler, mocks = _makeHandler(
            chatSettings=_makeChatSettings(embeddingModel="text-embedding-3-small"),
        )
        mockModel = Mock()
        mockModel.supportsEmbedding = True
        mockModel.generateEmbeddings = AsyncMock(side_effect=RuntimeError("API down"))
        _stubEmbeddingModel(handler, mockModel)
        mocks["db"].chatSearch.searchChatMessages = AsyncMock(return_value=[])

        await _callSearch(handler, _makeEnsuredMessage(), "keywords: meeting")

        # ``generateEmbeddings`` was attempted (and raised).
        mockModel.generateEmbeddings.assert_awaited_once()
        # The repository call still happened, with no query embedding
        # — the filter-only fallback path. ``modelName`` is preserved
        # so the repository can still rank any stored embeddings.
        mocks["db"].chatSearch.searchChatMessages.assert_awaited_once()
        callKwargs = mocks["db"].chatSearch.searchChatMessages.call_args.kwargs
        assert callKwargs["queryEmbedding"] is None
        assert callKwargs["modelName"] == "text-embedding-3-small"

    async def test_semantic_search_skips_if_model_not_found(self) -> None:
        """``getModel`` returning ``None`` → handler skips the embedding step.

        The chat has an ``EMBEDDING_MODEL`` set, but the model is not
        registered with the LLM manager (e.g. it was uninstalled
        between config and runtime). The handler must treat this as
        "no embedding available" and fall through to the filter-only
        path rather than crashing or trying to call methods on
        ``None``. ``modelName`` is still passed so the repository can
        load any stored embeddings for ranking.
        """
        handler, mocks = _makeHandler(
            chatSettings=_makeChatSettings(embeddingModel="missing-model"),
        )
        mockModel = Mock()
        mockModel.supportsEmbedding = True
        mockModel.generateEmbeddings = AsyncMock()
        # ``getModel`` returns None — simulate the model not being registered.
        cast(Any, handler).llmService.getLLMManager = Mock(return_value=Mock(getModel=Mock(return_value=None)))
        mocks["db"].chatSearch.searchChatMessages = AsyncMock(return_value=[])

        await _callSearch(handler, _makeEnsuredMessage(), "keywords: meeting")

        # The model mock's ``generateEmbeddings`` is never reached.
        mockModel.generateEmbeddings.assert_not_called()
        # The repository call still happens, with ``queryEmbedding=None``
        # (matching the empty-setting / model-missing path). ``modelName``
        # is preserved for stored-embedding ranking.
        mocks["db"].chatSearch.searchChatMessages.assert_awaited_once()
        callKwargs = mocks["db"].chatSearch.searchChatMessages.call_args.kwargs
        assert callKwargs["queryEmbedding"] is None
        assert callKwargs["modelName"] == "missing-model"


# ---------------------------------------------------------------------------
# 3. Backfill CRON_JOB tests
# ---------------------------------------------------------------------------


class TestDtCronJob:
    """Tests for :meth:`ChatSearchHandler._dtCronJob` (embedding backfill).

    Covers the construction-time gate (``[search-history].enabled``),
    the per-chat round-robin, the embedding model resolution, the
    per-batch fetch + embed loop, and the per-message error isolation.
    The handler is constructed with the real ``LLMService`` singleton
    (the autouse ``resetLlmServiceSingleton`` fixture has reset it),
    and the database stubs are added on top.
    """

    async def test_cron_proceeds_after_construction(self) -> None:
        """The cron job always runs its chat-discovery logic, regardless of ``enabled``.

        The `[search-history].enabled` flag is a construction-time gate
        enforced in ``HandlersManager`` (see ``manager.py:531``) — the
        handler is only instantiated when the feature is enabled. The
        cron job itself does not re-check the flag. With ``enabled=False``
        the cron job still attempts its normal chat-discovery logic; if
        no chat discovery mock is set up, the underlying call raises
        and is caught by the ``except`` around ``listChatsBySetting``.
        """
        cm = _makeConfigManager(enabled=False)
        handler, mocks = _makeHandler(configManager=cm)
        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )

        # The cron job does attempt chat discovery regardless of the
        # ``enabled`` flag — the flag is a construction-time gate only.
        # ``listChatsBySetting`` is a plain Mock, so awaiting it raises,
        # but that exception is caught by the try/except in ``_dtCronJob``.
        mocks["db"].chatSettings.listChatsBySetting.assert_called_once()
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings.assert_not_called()

    async def test_cron_no_enabled_chats(self) -> None:
        """No chats with ``EMBEDDINGS_ENABLED=true`` → backfill is a no-op.

        The backfill chat-discovery query targets the per-chat
        ``EMBEDDINGS_ENABLED`` setting (not ``REGENERATE_EMBEDDINGS`` —
        a chat that only enables new-message embeddings has no need
        for a backfill pass over its history). An empty result short-
        circuits the tick before any batch fetch or embedding call.
        """
        handler, mocks = _makeHandler()
        mocks["db"].chatSettings.listChatsBySetting = AsyncMock(return_value={})
        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )

        # The discovery query targets EMBEDDINGS_ENABLED specifically.
        mocks["db"].chatSettings.listChatsBySetting.assert_awaited_once_with(key=ChatSettingsKey.EMBEDDINGS_ENABLED)
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings.assert_not_called()

    async def test_cron_skips_when_embedding_model_missing(self) -> None:
        """A chat with no ``EMBEDDING_MODEL`` setting is skipped silently.

        ``REGENERATE_EMBEDDINGS=true`` but no model name means the chat
        has no model to embed with, so the backfill moves on without
        touching the embedding API.
        """
        cs = _makeChatSettings(embeddingModel="")
        handler, mocks = _makeHandler(chatSettings=cs)
        mocks["db"].chatSettings.listChatsBySetting = AsyncMock(return_value={100: "true"})
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings = AsyncMock()
        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )

        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings.assert_not_called()

    async def test_cron_skips_when_model_not_registered(self) -> None:
        """An unknown ``EMBEDDING_MODEL`` is skipped (model not in LLM manager)."""
        cs = _makeChatSettings(embeddingModel="missing-model")
        handler, mocks = _makeHandler(chatSettings=cs)
        mocks["db"].chatSettings.listChatsBySetting = AsyncMock(return_value={100: "true"})
        cast(Any, handler).llmService.getLLMManager = Mock(return_value=Mock(getModel=Mock(return_value=None)))
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings = AsyncMock()
        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )

        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings.assert_not_called()

    async def test_cron_skips_when_model_lacks_embedding_support(self) -> None:
        """A registered model that does not support embeddings is skipped."""
        cs = _makeChatSettings(embeddingModel="chat-only-model")
        handler, mocks = _makeHandler(chatSettings=cs)
        mocks["db"].chatSettings.listChatsBySetting = AsyncMock(return_value={100: "true"})
        mockModel = Mock()
        mockModel.supportsEmbedding = False
        mockModel.generateEmbeddings = AsyncMock()
        cast(Any, handler).llmService.getLLMManager = Mock(return_value=Mock(getModel=Mock(return_value=mockModel)))
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings = AsyncMock()
        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )

        mockModel.generateEmbeddings.assert_not_called()
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings.assert_not_called()

    def _makePendingMessage(
        self,
        *,
        messageId: MessageId = MessageId(1),
        messageText: str = "default text",
        chatId: int = 100,
        userId: int = 7,
        username: str = "alice",
        fullName: str = "Alice",
    ) -> Dict[str, Any]:
        """Build a :class:`ChatMessageDict`-shaped row for backfill tests.

        ``EnsuredMessage.fromDBChatMessage`` (used by the backfill loop
        to reconstruct an ``EnsuredMessage`` from the pending-message
        row) accesses many fields beyond ``message_id`` and
        ``message_text`` — every column from the ``chat_messages`` table.
        This helper provides a fully populated dict with sensible
        defaults so the factory method does not hit a ``KeyError``.

        Args:
            messageId: Value for ``message_id``.
            messageText: Value for ``message_text``.
            chatId: Value for ``chat_id`` (default 100).
            userId: Value for ``user_id`` (default 7).
            username: Value for ``username`` (default ``"alice"``).
            fullName: Value for ``full_name`` (default ``"Alice"``).

        Returns:
            Dict matching the shape ``EnsuredMessage.fromDBChatMessage``
            expects, with nullable fields set to ``None`` or sensible
            falsy defaults.
        """
        return {
            "chat_id": chatId,
            "message_id": messageId,
            "date": datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
            "user_id": userId,
            "reply_id": None,
            "thread_id": 0,
            "root_message_id": None,
            "message_text": messageText,
            "message_type": "text",
            "message_category": MessageCategory.USER,
            "quote_text": None,
            "media_id": None,
            "created_at": datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
            "metadata": "",
            "markup": "",
            "full_name": fullName,
            "username": username,
            "media_group_id": None,
        }

    async def test_cron_embeds_pending_messages(self) -> None:
        """A normal tick: the batch is fetched and each message is embedded + saved.

        Verifies:
        1. The configured ``EMBEDDING_MODEL`` is resolved via
           ``llmService.getLLMManager().getModel(name)``.
        2. The DB batch is fetched with the default batch size
           (``BACKFILL_DEFAULT_BATCH_SIZE``) when no explicit
           ``reindex-batch-size`` is configured, and the chat's
           ``EMBEDDING_MODEL`` is forwarded as ``modelName`` so rows
           embedded under a previous model are re-surfaced.
        3. Each pending message is embedded via the shared
           ``embedAndSaveMessage`` helper, which calls
           ``model.generateEmbeddings`` and then persists the vector
           via ``chatEmbeddings.saveMessageEmbedding`` with the
           matching ``model`` name (so a future model swap triggers
           a re-embed for the old rows).
        """
        cs = _makeChatSettings(embeddingModel="text-embedding-3-small")
        handler, mocks = _makeHandler(chatSettings=cs)
        mocks["db"].chatSettings.listChatsBySetting = AsyncMock(return_value={100: "true"})
        mockModel = Mock()
        mockModel.supportsEmbedding = True
        mockModel.generateEmbeddings = AsyncMock(side_effect=lambda text: [0.1, 0.2, 0.3])
        mockManager = Mock(getModel=Mock(return_value=mockModel))
        cast(Any, handler).llmService.getLLMManager = Mock(return_value=mockManager)
        pairs = [
            self._makePendingMessage(messageId=MessageId(1), messageText="hello world"),
            self._makePendingMessage(messageId=MessageId(2), messageText="another message"),
        ]
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings = AsyncMock(return_value=pairs)
        saveMock = AsyncMock()
        cast(Any, mocks["db"]).chatEmbeddings.saveMessageEmbedding = saveMock
        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )

        # The configured model name was resolved.
        mockManager.getModel.assert_called_with("text-embedding-3-small")
        # The batch was fetched with the default batch size and the
        # chat's embedding model forwarded as ``modelName`` so a model
        # swap re-surfaces rows embedded under the previous model.
        getKwargs = mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings.call_args.kwargs
        assert getKwargs["limit"] == BACKFILL_DEFAULT_BATCH_SIZE
        assert getKwargs["modelName"] == "text-embedding-3-small"
        # Each message was embedded by the model and the result saved
        # through ``embedAndSaveMessage`` → ``saveMessageEmbedding``.
        assert mockModel.generateEmbeddings.await_count == 2
        assert saveMock.await_count == 2
        # ``saveMessageEmbedding`` is invoked with keyword args
        # (see ``embedAndSaveMessage``), so we assert on ``kwargs``.
        saveKwargs = saveMock.await_args_list[0].kwargs
        assert saveKwargs["chatId"] == 100
        assert saveKwargs["model"] == "text-embedding-3-small"
        assert saveKwargs["embedding"] == [0.1, 0.2, 0.3]

    async def test_cron_per_message_error_does_not_abort_batch(self) -> None:
        """A single bad row never aborts the rest of the batch.

        Verifies the per-message isolation in the shared
        ``embedAndSaveMessage`` helper: the helper catches every
        error and returns ``False`` on failure, so the loop continues
        with the remaining messages. The other rows in the batch
        must still be embedded and saved.
        """
        cs = _makeChatSettings(embeddingModel="text-embedding-3-small")
        handler, mocks = _makeHandler(chatSettings=cs)
        mocks["db"].chatSettings.listChatsBySetting = AsyncMock(return_value={100: "true"})
        mockModel = Mock()
        mockModel.supportsEmbedding = True
        # First call raises, second call succeeds.
        mockModel.generateEmbeddings = AsyncMock(side_effect=[RuntimeError("embedder down"), [0.4, 0.5, 0.6]])
        cast(Any, handler).llmService.getLLMManager = Mock(return_value=Mock(getModel=Mock(return_value=mockModel)))
        pairs = [
            self._makePendingMessage(messageId=MessageId(1), messageText="bad message"),
            self._makePendingMessage(messageId=MessageId(2), messageText="good message"),
        ]
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings = AsyncMock(return_value=pairs)
        saveMock = AsyncMock()
        cast(Any, mocks["db"]).chatEmbeddings.saveMessageEmbedding = saveMock
        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )

        # Both messages were attempted despite the first one's failure.
        assert mockModel.generateEmbeddings.await_count == 2
        # Only the successful row was saved.
        assert saveMock.await_count == 1
        # ``saveMessageEmbedding`` is invoked with keyword args via
        # ``embedAndSaveMessage``.
        saveKwargs = saveMock.await_args_list[0].kwargs
        assert saveKwargs["chatId"] == 100
        assert saveKwargs["messageId"] == MessageId(2)
        assert saveKwargs["embedding"] == [0.4, 0.5, 0.6]

    async def test_cron_respects_configured_batch_size(self) -> None:
        """``[search-history.embeddings].reindex-batch-size`` is honoured.

        A custom batch size set in the merged config overrides the
        ``BACKFILL_DEFAULT_BATCH_SIZE`` default.
        """
        cm = Mock()
        cm.getBotConfig = Mock(return_value={"token": "test", "owners": []})
        cm.getSearchHistoryConfig = Mock(
            return_value={
                "enabled": True,
                "defaults": {"max-results": 10, "default-days": 30},
                "embeddings": {"reindex-batch-size": 7},
            }
        )
        cs = _makeChatSettings(embeddingModel="text-embedding-3-small")
        handler, mocks = _makeHandler(configManager=cm, chatSettings=cs)
        mocks["db"].chatSettings.listChatsBySetting = AsyncMock(return_value={100: "true"})
        mockModel = Mock()
        mockModel.supportsEmbedding = True
        mockModel.generateEmbeddings = AsyncMock(return_value=[0.1])
        cast(Any, handler).llmService.getLLMManager = Mock(return_value=Mock(getModel=Mock(return_value=mockModel)))
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings = AsyncMock(return_value=[])
        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )

        getKwargs = mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings.call_args.kwargs
        assert getKwargs["limit"] == 7

    async def test_cron_round_robin_across_chats(self) -> None:
        """Subsequent ticks pick the next chat in stable order.

        The backfill index is a per-instance counter that advances on
        every tick; with two enabled chats the second tick must pick
        the second chat. The first tick always picks index 0.
        """
        cs = _makeChatSettings(embeddingModel="text-embedding-3-small")
        handler, mocks = _makeHandler(chatSettings=cs)
        mocks["db"].chatSettings.listChatsBySetting = AsyncMock(return_value={100: "true", 200: "true"})
        mockModel = Mock()
        mockModel.supportsEmbedding = True
        mockModel.generateEmbeddings = AsyncMock(return_value=[0.1])
        cast(Any, handler).llmService.getLLMManager = Mock(return_value=Mock(getModel=Mock(return_value=mockModel)))
        # Empty batch — we just want to assert which chat was picked.
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings = AsyncMock(return_value=[])

        # Tick 1: picks chat 100.
        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )
        firstGetArgs = mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings.call_args.args
        assert firstGetArgs[0] == 100
        # Tick 2: picks chat 200.
        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )
        secondGetArgs = mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings.call_args.args
        assert secondGetArgs[0] == 200

    async def test_cron_early_return_on_empty_backlog(self) -> None:
        """Backfill CRON_JOB returns early when no pending messages exist.

        The handler no longer performs any self-reset of
        ``REGENERATE_EMBEDDINGS`` — the per-tick batch is small and
        the next minute's tick will pick up where this one left off.
        """
        cs = _makeChatSettings(embeddingModel="text-embedding-3-small")
        handler, mocks = _makeHandler(chatSettings=cs)
        mocks["db"].chatSettings.listChatsBySetting = AsyncMock(return_value={100: "true"})
        mockModel = Mock()
        mockModel.supportsEmbedding = True
        mockModel.generateEmbeddings = AsyncMock(return_value=[0.1])
        cast(Any, handler).llmService.getLLMManager = Mock(return_value=Mock(getModel=Mock(return_value=mockModel)))
        # Empty backlog — no pending messages to embed.
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings = AsyncMock(return_value=[])
        # Set up setChatSetting on the mock so we can assert it was NOT called.
        mocks["db"].chatSettings.setChatSetting = AsyncMock()

        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )

        # The handler returns early on empty backlog — no self-reset.
        mocks["db"].chatSettings.setChatSetting.assert_not_called()

    async def test_cron_self_reset_does_not_fire_on_full_batch(self) -> None:
        """``REGENERATE_EMBEDDINGS`` is NOT reset when the backlog has a full batch.

        When the repo returns exactly ``_reindexBatchSize`` messages,
        the backlog is not yet drained — there may be more messages
        beyond this batch. The self-reset must NOT fire so the next
        tick continues backfilling.
        """
        cs = _makeChatSettings(embeddingModel="text-embedding-3-small")
        handler, mocks = _makeHandler(chatSettings=cs)
        mocks["db"].chatSettings.listChatsBySetting = AsyncMock(return_value={100: "true"})
        mockModel = Mock()
        mockModel.supportsEmbedding = True
        mockModel.generateEmbeddings = AsyncMock(return_value=[0.1])
        cast(Any, handler).llmService.getLLMManager = Mock(return_value=Mock(getModel=Mock(return_value=mockModel)))
        # Exactly _reindexBatchSize messages — backlog not yet drained.
        fullBatch = [self._makePendingMessage(messageId=MessageId(i)) for i in range(BACKFILL_DEFAULT_BATCH_SIZE)]
        mocks["db"].chatEmbeddings.getMessagesWithoutEmbeddings = AsyncMock(return_value=fullBatch)
        # Stub saveMessageEmbedding so the embedding loop runs cleanly.
        saveMock = AsyncMock()
        cast(Any, mocks["db"]).chatEmbeddings.saveMessageEmbedding = saveMock
        # Set up setChatSetting so we can assert it was NOT called.
        mocks["db"].chatSettings.setChatSetting = AsyncMock()

        await handler._dtCronJob(
            DelayedTask(
                taskId=f"cron-{id(self)}",
                delayedUntil=0.0,
                function=DelayedTaskFunction.CRON_JOB,
                kwargs={},
            )
        )

        # The self-reset must NOT fire when the batch is full.
        mocks["db"].chatSettings.setChatSetting.assert_not_called()


# ---------------------------------------------------------------------------
# 4. LLM tool: search_messages tests
# ---------------------------------------------------------------------------


class TestSearchMessagesLLMTool:
    """Tests for :meth:`ChatSearchHandler._llmToolSearchMessages`."""

    @pytest.fixture
    def handler(self) -> ChatSearchHandler:
        """Create a handler with mocked dependencies for LLM tool tests."""
        h = ChatSearchHandler(
            configManager=_makeConfigManager(),
            database=_makeDatabase(),
            botProvider=BotProvider.TELEGRAM,
        )
        h.db = Mock()
        h.llmService = Mock()
        cast(Any, h).llmService.rateLimit = AsyncMock(return_value=None)
        h.sendMessage = AsyncMock()
        h.getChatSettings = AsyncMock()
        return h

    @pytest.fixture
    def ensMessage(self) -> EnsuredMessage:
        """Create a test ensured message in a group chat."""
        return _makeEnsuredMessage(chatId=-1001234567890)

    @pytest.fixture
    def extraData(self, ensMessage: EnsuredMessage) -> Dict[str, Any]:
        """Create extraData dict with the ensured message."""
        return {"ensuredMessage": ensMessage}

    @pytest.fixture
    def chatSettings(self) -> ChatSettingsDict:
        """Chat settings with tools, embeddings, and model configured."""
        return _makeChatSettings(embeddingModel="text-embedding-3-small")

    @pytest.fixture
    def mockModel(self) -> Mock:
        """A mock embedding model that supports embeddings."""
        m = Mock()
        m.supportsEmbedding = True
        m.generateEmbeddings = AsyncMock(return_value=[0.1, 0.2, 0.3])
        return m

    def _stubModel(self, handler: ChatSearchHandler, model: Mock) -> Mock:
        """Wire a mock embedding model into the handler's LLM service.

        Args:
            handler: Handler under test.
            model: Mock model instance.

        Returns:
            The mock manager.
        """
        mockManager = Mock()
        mockManager.getModel = Mock(return_value=model)
        cast(Any, handler).llmService.getLLMManager = Mock(return_value=mockManager)
        return mockManager

    async def test_search_messages_missing_extraData(self, handler: ChatSearchHandler) -> None:
        """extraData is None → returns error dict."""
        result = await handler._llmToolSearchMessages(extraData=None, query="test")
        assert result["done"] is False
        assert "Missing chat context" in result.get("error", "")

    async def test_search_messages_missing_ensuredMessage(self, handler: ChatSearchHandler) -> None:
        """extraData has no ensuredMessage → returns error dict."""
        result = await handler._llmToolSearchMessages(extraData={}, query="test")
        assert result["done"] is False
        assert "Missing chat context" in result.get("error", "")

    async def test_search_messages_tools_disabled(self, handler: ChatSearchHandler, extraData: Dict[str, Any]) -> None:
        """ALLOW_TOOLS_COMMANDS=False → returns error dict."""
        cs = _makeChatSettings(allowTools=False, embeddingModel="text-embedding-3-small")
        handler.getChatSettings = AsyncMock(return_value=cs)
        result = await handler._llmToolSearchMessages(extraData=extraData, query="test")
        assert result["done"] is False
        assert "tools disabled" in result.get("error", "").lower()

    async def test_search_messages_embeddings_disabled(
        self, handler: ChatSearchHandler, extraData: Dict[str, Any]
    ) -> None:
        """EMBEDDINGS_ENABLED=False → returns error dict."""
        cs = _makeChatSettings(embeddingsEnabled=False, embeddingModel="text-embedding-3-small")
        handler.getChatSettings = AsyncMock(return_value=cs)
        result = await handler._llmToolSearchMessages(extraData=extraData, query="test")
        assert result["done"] is False
        assert "semantic search" in result.get("error", "").lower()

    async def test_search_messages_no_model(
        self, handler: ChatSearchHandler, extraData: Dict[str, Any], chatSettings: ChatSettingsDict
    ) -> None:
        """EMBEDDING_MODEL is empty → returns error dict."""
        cs = _makeChatSettings(embeddingModel="")
        handler.getChatSettings = AsyncMock(return_value=cs)
        result = await handler._llmToolSearchMessages(extraData=extraData, query="test")
        assert result["done"] is False
        assert "not configured" in result.get("error", "").lower()

    async def test_search_messages_success(
        self,
        handler: ChatSearchHandler,
        extraData: Dict[str, Any],
        chatSettings: ChatSettingsDict,
        mockModel: Mock,
    ) -> None:
        """Full happy path: returns results dict with done=True."""
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        self._stubModel(handler, mockModel)
        now = datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)
        rows = [
            {
                "chat_id": -1001234567890,
                "message_id": MessageId(1),
                "date": now,
                "user_id": 7,
                "reply_id": None,
                "thread_id": 0,
                "root_message_id": None,
                "message_text": "hello world",
                "message_type": "text",
                "message_category": MessageCategory.USER,
                "quote_text": None,
                "media_id": None,
                "created_at": now,
                "metadata": "",
                "markup": "",
                "media_group_id": None,
                "username": "alice",
                "full_name": "Alice",
                "score": 0.95,
            }
        ]
        cast(Any, handler).db.chatSearch = Mock()
        cast(Any, handler).db.chatSearch.searchChatMessages = AsyncMock(return_value=rows)

        result = await handler._llmToolSearchMessages(extraData=extraData, query="hello")

        assert result["done"] is True
        assert result["count"] == 1
        assert result["results"][0]["text"] == "hello world"
        assert result["results"][0]["score"] == 0.95
        mockModel.generateEmbeddings.assert_awaited_once()

    async def test_search_messages_with_user_filter(
        self,
        handler: ChatSearchHandler,
        extraData: Dict[str, Any],
        chatSettings: ChatSettingsDict,
        mockModel: Mock,
    ) -> None:
        """user_name resolves to userId and is passed to searchChatMessages."""
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        self._stubModel(handler, mockModel)
        cast(Any, handler).db.chatUsers = Mock()
        cast(Any, handler).db.chatUsers.getChatUserByUsername = AsyncMock(return_value={"user_id": 42})
        cast(Any, handler).db.chatSearch = Mock()
        cast(Any, handler).db.chatSearch.searchChatMessages = AsyncMock(return_value=[])

        await handler._llmToolSearchMessages(extraData=extraData, query="test", user_name="@bob")

        callKwargs = cast(Any, handler).db.chatSearch.searchChatMessages.call_args.kwargs
        assert callKwargs["userFilter"] == 42

    async def test_search_messages_embedding_failure(
        self,
        handler: ChatSearchHandler,
        extraData: Dict[str, Any],
        chatSettings: ChatSettingsDict,
    ) -> None:
        """generateEmbeddings raises → returns error dict."""
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        badModel = Mock()
        badModel.supportsEmbedding = True
        badModel.generateEmbeddings = AsyncMock(side_effect=RuntimeError("API down"))
        self._stubModel(handler, badModel)

        result = await handler._llmToolSearchMessages(extraData=extraData, query="hello")

        assert result["done"] is False
        assert "embedding" in result.get("error", "").lower()


# ---------------------------------------------------------------------------
# 5. LLM tool: list_users tests
# ---------------------------------------------------------------------------


class TestListUsersLLMTool:
    """Tests for :meth:`ChatSearchHandler._llmToolListUsers`."""

    @pytest.fixture
    def handler(self) -> ChatSearchHandler:
        """Create a handler with mocked dependencies."""
        h = ChatSearchHandler(
            configManager=_makeConfigManager(),
            database=_makeDatabase(),
            botProvider=BotProvider.TELEGRAM,
        )
        h.db = Mock()
        h.llmService = Mock()
        h.sendMessage = AsyncMock()
        h.getChatSettings = AsyncMock()
        cast(Any, h).db.chatUsers = Mock()
        return h

    @pytest.fixture
    def ensMessage(self) -> EnsuredMessage:
        """Create a test ensured message in a group chat."""
        return _makeEnsuredMessage(chatId=-1001234567890)

    @pytest.fixture
    def extraData(self, ensMessage: EnsuredMessage) -> Dict[str, Any]:
        """Create extraData dict with the ensured message."""
        return {"ensuredMessage": ensMessage}

    @pytest.fixture
    def chatSettings(self) -> ChatSettingsDict:
        """Chat settings with tools enabled."""
        return _makeChatSettings()

    @pytest.fixture
    def sampleUsers(self) -> List[Dict[str, Any]]:
        """Sample user dicts matching ChatUserDict shape."""
        now = datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)
        return [
            {
                "chat_id": -1001234567890,
                "user_id": 1,
                "username": "alice",
                "full_name": "Alice",
                "timezone": None,
                "messages_count": 150,
                "metadata": "",
                "created_at": now,
                "updated_at": now,
            },
            {
                "chat_id": -1001234567890,
                "user_id": 2,
                "username": "bob",
                "full_name": "Bob",
                "timezone": None,
                "messages_count": 75,
                "metadata": "",
                "created_at": now,
                "updated_at": now,
            },
        ]

    async def test_list_users_missing_extraData(self, handler: ChatSearchHandler) -> None:
        """extraData is None → returns error dict."""
        result = await handler._llmToolListUsers(extraData=None)
        assert result["done"] is False
        assert "Missing chat context" in result.get("error", "")

    async def test_list_users_tools_disabled(self, handler: ChatSearchHandler, extraData: Dict[str, Any]) -> None:
        """ALLOW_TOOLS_COMMANDS=False → returns error dict."""
        cs = _makeChatSettings(allowTools=False)
        handler.getChatSettings = AsyncMock(return_value=cs)
        result = await handler._llmToolListUsers(extraData=extraData)
        assert result["done"] is False
        assert "отключены" in result.get("error", "").lower()

    async def test_list_users_success(
        self,
        handler: ChatSearchHandler,
        extraData: Dict[str, Any],
        chatSettings: ChatSettingsDict,
        sampleUsers: List[Dict[str, Any]],
    ) -> None:
        """Returns users list with proper format."""
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(return_value=sampleUsers)

        result = await handler._llmToolListUsers(extraData=extraData)

        assert result["done"] is True
        assert result["count"] == 2
        assert result["users"][0]["user_id"] == 1
        assert result["users"][0]["username"] == "alice"
        assert result["users"][0]["messages_count"] == 150
        assert "last_active" in result["users"][0]
        assert result["users"][1]["user_id"] == 2

    async def test_list_users_empty(
        self,
        handler: ChatSearchHandler,
        extraData: Dict[str, Any],
        chatSettings: ChatSettingsDict,
    ) -> None:
        """Empty user list → done=True, users=[], count=0."""
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(return_value=[])

        result = await handler._llmToolListUsers(extraData=extraData)

        assert result["done"] is True
        assert result["users"] == []
        assert result["count"] == 0

    async def test_list_users_handles_getChatSettings_error(
        self, handler: ChatSearchHandler, extraData: Dict[str, Any]
    ) -> None:
        """getChatSettings raises → returns error dict."""
        handler.getChatSettings = AsyncMock(side_effect=RuntimeError("DB down"))
        result = await handler._llmToolListUsers(extraData=extraData)
        assert result["done"] is False
        assert "настройки" in result.get("error", "")

    async def test_list_users_forwards_params(
        self,
        handler: ChatSearchHandler,
        extraData: Dict[str, Any],
        chatSettings: ChatSettingsDict,
    ) -> None:
        """limit and min_messages are forwarded to getChatUsers."""
        mockUsers = [
            {
                "user_id": 1,
                "username": "@test",
                "full_name": "Test",
                "messages_count": 50,
                "updated_at": datetime.datetime(2026, 6, 20, 12, 0, 0, tzinfo=datetime.timezone.utc),
            }
        ]
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(return_value=mockUsers)

        result = await handler._llmToolListUsers(extraData=extraData, limit=7, min_messages=3)

        assert result["done"] is True
        calledKwargs = cast(Any, handler).db.chatUsers.getChatUsers.call_args.kwargs
        assert calledKwargs["limit"] == 7
        assert calledKwargs["minMessages"] == 3

    async def test_list_users_updated_at_none(
        self,
        handler: ChatSearchHandler,
        extraData: Dict[str, Any],
        chatSettings: ChatSettingsDict,
    ) -> None:
        """updated_at is None → last_active is '' not 'None'."""
        mockUsers = [
            {
                "user_id": 1,
                "username": "alice",
                "full_name": "Alice",
                "messages_count": 10,
                "updated_at": None,
            }
        ]
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(return_value=mockUsers)

        result = await handler._llmToolListUsers(extraData=extraData)

        assert result["done"] is True
        assert result["users"][0]["last_active"] == ""

    async def test_list_users_repo_raises(
        self,
        handler: ChatSearchHandler,
        extraData: Dict[str, Any],
        chatSettings: ChatSettingsDict,
    ) -> None:
        """Repository exception → error dict."""
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(side_effect=RuntimeError("DB down"))

        result = await handler._llmToolListUsers(extraData=extraData)

        assert result["done"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# 6. LLM tool: get_thread tests
# ---------------------------------------------------------------------------


class TestGetThreadLLMTool:
    """Tests for :meth:`ChatSearchHandler._llmToolGetThread`."""

    @pytest.fixture
    def handler(self) -> ChatSearchHandler:
        """Create a handler with mocked dependencies."""
        h = ChatSearchHandler(
            configManager=_makeConfigManager(),
            database=_makeDatabase(),
            botProvider=BotProvider.TELEGRAM,
        )
        h.db = Mock()
        h.llmService = Mock()
        cast(Any, h).llmService.rateLimit = AsyncMock(return_value=None)
        h.sendMessage = AsyncMock()
        h.getChatSettings = AsyncMock()
        cast(Any, h).db.chatMessages = Mock()
        # Default: getMessageThread returns None (message not found).
        # Individual tests override for success cases.
        cast(Any, h).db.chatMessages.getMessageThread = AsyncMock(return_value=None)
        return h

    @pytest.fixture
    def ensMessage(self) -> EnsuredMessage:
        """Create a test ensured message in a group chat."""
        return _makeEnsuredMessage(chatId=-1001234567890)

    @pytest.fixture
    def extraData(self, ensMessage: EnsuredMessage) -> Dict[str, Any]:
        """Create extraData dict with the ensured message."""
        return {"ensuredMessage": ensMessage}

    @pytest.fixture
    def chatSettings(self) -> ChatSettingsDict:
        """Chat settings with tools enabled."""
        return _makeChatSettings()

    @pytest.fixture
    def sampleMessage(self) -> ChatMessageDict:
        """A sample chat message dict for building thread fixtures."""
        return {
            "chat_id": -1001234567890,
            "message_id": MessageId(10),
            "date": datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
            "user_id": 1,
            "reply_id": None,
            "thread_id": 0,
            "root_message_id": None,
            "message_text": "Root message",
            "message_type": "text",
            "message_category": MessageCategory.USER,
            "quote_text": None,
            "media_id": None,
            "created_at": datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
            "metadata": "",
            "markup": "",
            "media_group_id": None,
            "username": "alice",
            "full_name": "Alice",
        }

    async def test_get_thread_missing_extraData(self, handler: ChatSearchHandler) -> None:
        """extraData is None → returns error dict."""
        result = await handler._llmToolGetThread(extraData=None, message_id="10")
        assert result["done"] is False
        assert "Missing chat context" in result.get("error", "")

    async def test_get_thread_tools_disabled(self, handler: ChatSearchHandler, extraData: Dict[str, Any]) -> None:
        """ALLOW_TOOLS_COMMANDS=False → returns error dict."""
        cs = _makeChatSettings(allowTools=False)
        handler.getChatSettings = AsyncMock(return_value=cs)
        result = await handler._llmToolGetThread(extraData=extraData, message_id="10")
        assert result["done"] is False
        assert "отключены" in result.get("error", "").lower()

    async def test_get_thread_invalid_message_id(
        self, handler: ChatSearchHandler, extraData: Dict[str, Any], chatSettings: ChatSettingsDict
    ) -> None:
        """Invalid message_id value (None) → returns error dict."""
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        # Pass None — MessageId(None) raises ValueError/TypeError and is
        # caught by Gate 3's except block, returning "неверный".
        result = await cast(Any, handler)._llmToolGetThread(extraData=extraData, message_id=None)
        assert result["done"] is False
        assert "неверный" in result.get("error", "").lower()

    async def test_get_thread_not_found(
        self, handler: ChatSearchHandler, extraData: Dict[str, Any], chatSettings: ChatSettingsDict
    ) -> None:
        """getMessageThread returns None → returns error dict."""
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        cast(Any, handler).db.chatMessages.getMessageThread = AsyncMock(return_value=None)
        result = await handler._llmToolGetThread(extraData=extraData, message_id="9999")
        assert result["done"] is False
        assert "не найдено" in result.get("error", "").lower()

    async def test_get_thread_success(
        self,
        handler: ChatSearchHandler,
        extraData: Dict[str, Any],
        chatSettings: ChatSettingsDict,
        sampleMessage: ChatMessageDict,
    ) -> None:
        """Returns thread with root/target/messages properly formatted."""
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        rootMsg = dict(sampleMessage)
        rootMsg["message_id"] = MessageId(5)
        rootMsg["message_text"] = "Thread root"
        targetMsg = dict(sampleMessage)
        targetMsg["message_id"] = MessageId(10)
        targetMsg["message_text"] = "Reply message"
        targetMsg["root_message_id"] = MessageId(5)
        targetMsg["reply_id"] = MessageId(5)
        replyMsg = dict(sampleMessage)
        replyMsg["message_id"] = MessageId(11)
        replyMsg["message_text"] = "Another reply"
        replyMsg["root_message_id"] = MessageId(5)
        replyMsg["reply_id"] = MessageId(10)

        threadResult = {
            "root_message": rootMsg,
            "target_message": targetMsg,
            "thread_messages": [rootMsg, targetMsg, replyMsg],
        }
        cast(Any, handler).db.chatMessages.getMessageThread = AsyncMock(return_value=threadResult)

        result = await handler._llmToolGetThread(extraData=extraData, message_id="10")

        assert result["done"] is True
        assert result["root_message"] is not None
        assert result["root_message"]["messageId"] == 5
        assert result["root_message"]["text"] == "Thread root"
        assert result["target_message"]["messageId"] == 10
        assert result["target_message"]["text"] == "Reply message"
        assert len(result["thread_messages"]) == 3
        assert result["thread_messages"][1]["messageId"] == 10

    async def test_get_thread_root_message_none(
        self,
        handler: ChatSearchHandler,
        extraData: Dict[str, Any],
        chatSettings: ChatSettingsDict,
        sampleMessage: ChatMessageDict,
    ) -> None:
        """Target is a root message (no root_message_id) → root_message is None."""
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        targetMsg = dict(sampleMessage)
        targetMsg["message_id"] = MessageId(10)
        targetMsg["message_text"] = "I am the root"

        threadResult = {
            "root_message": None,
            "target_message": targetMsg,
            "thread_messages": [targetMsg],
        }
        cast(Any, handler).db.chatMessages.getMessageThread = AsyncMock(return_value=threadResult)

        result = await handler._llmToolGetThread(extraData=extraData, message_id="10")

        assert result["done"] is True
        assert result["root_message"] is None
        assert result["target_message"]["messageId"] == 10
        assert len(result["thread_messages"]) == 1

    async def test_get_thread_getMessageThread_raises(
        self, handler: ChatSearchHandler, extraData: Dict[str, Any], chatSettings: ChatSettingsDict
    ) -> None:
        """getMessageThread raises → returns error dict."""
        handler.getChatSettings = AsyncMock(return_value=chatSettings)
        cast(Any, handler).db.chatMessages.getMessageThread = AsyncMock(side_effect=RuntimeError("DB error"))
        result = await handler._llmToolGetThread(extraData=extraData, message_id="10")
        assert result["done"] is False
        assert "тред" in result.get("error", "").lower()

    async def test_get_thread_getChatSettings_raises(
        self, handler: ChatSearchHandler, extraData: Dict[str, Any]
    ) -> None:
        """getChatSettings raises → returns error dict."""
        handler.getChatSettings = AsyncMock(side_effect=RuntimeError("Settings error"))
        result = await handler._llmToolGetThread(extraData=extraData, message_id="10")
        assert result["done"] is False
        assert "настройки" in result.get("error", "")

    async def test_get_thread_handles_chat_context_error(self, handler: ChatSearchHandler) -> None:
        """extraData has no ensuredMessage → returns error dict."""
        result = await handler._llmToolGetThread(extraData={}, message_id="10")
        assert result["done"] is False
        assert "Missing chat context" in result.get("error", "")


# ---------------------------------------------------------------------------
# 7. User command tests
# ---------------------------------------------------------------------------


class TestUsersCommand:
    """Tests for :meth:`ChatSearchHandler.usersCommand`."""

    @pytest.fixture
    def handler(self) -> ChatSearchHandler:
        """Create a handler with mocked dependencies."""
        h = ChatSearchHandler(
            configManager=_makeConfigManager(),
            database=_makeDatabase(),
            botProvider=BotProvider.TELEGRAM,
        )
        h.db = Mock()
        h.llmService = Mock()
        h.sendMessage = AsyncMock()
        h.getChatSettings = AsyncMock()
        cast(Any, h).db.chatUsers = Mock()
        return h

    @pytest.fixture
    def ensMessage(self) -> EnsuredMessage:
        """Create a test ensured message in a group chat."""
        return _makeEnsuredMessage(chatId=-1001234567890)

    @pytest.fixture
    def sampleUsers(self) -> List[Dict[str, Any]]:
        """Sample user dicts matching ChatUserDict shape."""
        now = datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)
        return [
            {
                "chat_id": -1001234567890,
                "user_id": 1,
                "username": "alice",
                "full_name": "Alice",
                "timezone": None,
                "messages_count": 150,
                "metadata": "",
                "created_at": now,
                "updated_at": now,
            },
            {
                "chat_id": -1001234567890,
                "user_id": 2,
                "username": "bob",
                "full_name": "Bob",
                "timezone": None,
                "messages_count": 75,
                "metadata": "",
                "created_at": now,
                "updated_at": now,
            },
        ]

    def _callUsers(self, handler: ChatSearchHandler, ensuredMessage: EnsuredMessage, args: str = "") -> Any:
        """Invoke ``usersCommand`` past pyright's unbound-signature view.

        Args:
            handler: Handler under test.
            ensuredMessage: Originating user message.
            args: Raw arguments string after ``/users``.

        Returns:
            Whatever the underlying coroutine returns (always ``None``).
        """
        return cast(Any, handler).usersCommand(
            ensuredMessage,
            "users",
            args,
            updateObj=Mock(),
            typingManager=None,
        )

    async def test_users_command_no_args(
        self,
        handler: ChatSearchHandler,
        ensMessage: EnsuredMessage,
        sampleUsers: List[Dict[str, Any]],
    ) -> None:
        """/users with no args returns formatted user list."""
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(return_value=sampleUsers)

        await self._callUsers(handler, ensMessage)

        cast(Any, handler).sendMessage.assert_awaited_once()
        sentKwargs = cast(Any, handler).sendMessage.call_args.kwargs
        sentText: str = sentKwargs.get("messageText", "")
        assert "Участники" in sentText
        assert "alice" in sentText
        assert "Bob" in sentText
        assert "150" in sentText  # messages_count
        assert sentKwargs.get("messageCategory") == MessageCategory.BOT_COMMAND_REPLY

    async def test_users_command_empty(
        self,
        handler: ChatSearchHandler,
        ensMessage: EnsuredMessage,
    ) -> None:
        """No users in chat → sends 'Участники не найдены.'"""
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(return_value=[])

        await self._callUsers(handler, ensMessage)

        cast(Any, handler).sendMessage.assert_awaited_once()
        sentText: str = cast(Any, handler).sendMessage.call_args.kwargs.get("messageText", "")
        assert "не найдены" in sentText

    async def test_users_command_with_limit(
        self,
        handler: ChatSearchHandler,
        ensMessage: EnsuredMessage,
        sampleUsers: List[Dict[str, Any]],
    ) -> None:
        """/users limit=10 passes limit to _listUsersInternal."""
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(return_value=sampleUsers)

        await self._callUsers(handler, ensMessage, "limit=10")

        callKwargs = cast(Any, handler).db.chatUsers.getChatUsers.call_args.kwargs
        assert callKwargs["limit"] == 10

    async def test_users_command_with_min_messages(
        self,
        handler: ChatSearchHandler,
        ensMessage: EnsuredMessage,
        sampleUsers: List[Dict[str, Any]],
    ) -> None:
        """/users min_messages=100 passes minMessages filter."""
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(return_value=sampleUsers)

        await self._callUsers(handler, ensMessage, "min_messages=100")

        callKwargs = cast(Any, handler).db.chatUsers.getChatUsers.call_args.kwargs
        assert callKwargs["minMessages"] == 100

    async def test_users_command_with_last_active(
        self,
        handler: ChatSearchHandler,
        ensMessage: EnsuredMessage,
        sampleUsers: List[Dict[str, Any]],
    ) -> None:
        """/users last_active=7 passes lastActiveDays filter."""
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(return_value=sampleUsers)

        await self._callUsers(handler, ensMessage, "last_active=7")

        callKwargs = cast(Any, handler).db.chatUsers.getChatUsers.call_args.kwargs
        assert callKwargs["lastActiveDays"] == 7

    async def test_users_command_invalid_args(
        self,
        handler: ChatSearchHandler,
        ensMessage: EnsuredMessage,
        sampleUsers: List[Dict[str, Any]],
    ) -> None:
        """/users limit=abc uses default limit (50)."""
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(return_value=sampleUsers)

        await self._callUsers(handler, ensMessage, "limit=abc")

        callKwargs = cast(Any, handler).db.chatUsers.getChatUsers.call_args.kwargs
        assert callKwargs["limit"] == 50

    async def test_users_command_with_all_args(
        self,
        handler: ChatSearchHandler,
        ensMessage: EnsuredMessage,
        sampleUsers: List[Dict[str, Any]],
    ) -> None:
        """/users with all args passes all filters to _listUsersInternal."""
        cast(Any, handler).db.chatUsers.getChatUsers = AsyncMock(return_value=sampleUsers)

        await self._callUsers(handler, ensMessage, "limit=5 min_messages=10 last_active=30")

        callKwargs = cast(Any, handler).db.chatUsers.getChatUsers.call_args.kwargs
        assert callKwargs["limit"] == 5
        assert callKwargs["minMessages"] == 10
        assert callKwargs["lastActiveDays"] == 30


# ---------------------------------------------------------------------------
# 8. _formatMessageDict tests
# ---------------------------------------------------------------------------


class TestFormatMessageDict:
    """Tests for :meth:`ChatSearchHandler._formatMessageDict`."""

    @pytest.fixture
    def handler(self) -> ChatSearchHandler:
        """Create a handler with a mocked database for ``_formatMessageDict`` tests.

        The handler's ``db`` is a plain ``Mock`` — ``_formatMessageDict`` calls
        ``EnsuredMessage.fromDBChatMessage`` which needs ``self.db`` as a
        parameter, but the test message dicts have ``media_group_id=None`` and
        ``media_id=None`` so no DB methods are actually awaited.
        """
        h = ChatSearchHandler(
            configManager=_makeConfigManager(),
            database=_makeDatabase(),
            botProvider=BotProvider.TELEGRAM,
        )
        h.db = Mock()
        return h

    async def test_format_message_dict_basic(self, handler: ChatSearchHandler) -> None:
        """A fully populated ChatMessageDict is correctly formatted."""
        now = datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)
        msg: ChatMessageDict = {
            "chat_id": -1001234567890,
            "message_id": MessageId(42),
            "date": now,
            "user_id": 7,
            "reply_id": MessageId(10),
            "thread_id": 0,
            "root_message_id": MessageId(10),
            "message_text": "Hello world",
            "message_type": "text",
            "message_category": MessageCategory.USER,
            "quote_text": None,
            "media_id": None,
            "created_at": now,
            "metadata": "",
            "markup": "",
            "media_group_id": None,
            "username": "alice",
            "full_name": "Alice",
        }
        result = await handler._formatMessageDict(msg)
        assert result["messageId"] == 42
        assert result["text"] == "Hello world"
        assert result["login"] == "alice"
        assert result["name"] == "Alice"
        assert result["date"] == "2026-05-05T12:00:00+00:00"
        assert result["replyId"] == 10
        # Note: no thread_id key in production output

    async def test_format_message_dict_none_reply_id(self, handler: ChatSearchHandler) -> None:
        """reply_id=None → serialized as None (not 'None' string)."""
        now = datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)
        msg: ChatMessageDict = {
            "chat_id": -1001234567890,
            "message_id": MessageId(1),
            "date": now,
            "user_id": 1,
            "reply_id": None,
            "thread_id": 0,
            "root_message_id": None,
            "message_text": "test",
            "message_type": "text",
            "message_category": MessageCategory.USER,
            "quote_text": None,
            "media_id": None,
            "created_at": now,
            "metadata": "",
            "markup": "",
            "media_group_id": None,
            "username": "",
            "full_name": "",
        }
        result = await handler._formatMessageDict(msg)
        assert "replyId" not in result


class TestResolveUserId:
    """Tests for :meth:`ChatSearchHandler._resolveUserId`."""

    @pytest.fixture
    def handler(self) -> ChatSearchHandler:
        """Create a handler with mocked dependencies for resolve-user tests."""
        h = ChatSearchHandler(
            configManager=_makeConfigManager(),
            database=_makeDatabase(),
            botProvider=BotProvider.TELEGRAM,
        )
        h.db = Mock()
        h.llmService = Mock()
        h.sendMessage = AsyncMock()
        h.getChatSettings = AsyncMock()
        return h

    async def test_resolve_with_at_prefix(self, handler: ChatSearchHandler) -> None:
        """Username with @ is normalised to @username for DB lookup."""
        cast(Any, handler).db.chatUsers = Mock()
        cast(Any, handler).db.chatUsers.getChatUserByUsername = AsyncMock(return_value={"user_id": 123})

        result = await handler._resolveUserId(chatId=-100123, username="@testuser")

        assert result == 123
        cast(Any, handler).db.chatUsers.getChatUserByUsername.assert_called_once_with(
            chatId=-100123, username="@testuser"
        )

    async def test_resolve_without_at_prefix(self, handler: ChatSearchHandler) -> None:
        """Username without @ has @ prepended for DB lookup."""
        cast(Any, handler).db.chatUsers = Mock()
        cast(Any, handler).db.chatUsers.getChatUserByUsername = AsyncMock(return_value={"user_id": 456})

        result = await handler._resolveUserId(chatId=-100123, username="testuser")

        assert result == 456
        cast(Any, handler).db.chatUsers.getChatUserByUsername.assert_called_once_with(
            chatId=-100123, username="@testuser"
        )

    async def test_resolve_empty_after_strip(self, handler: ChatSearchHandler) -> None:
        """Username that becomes empty after stripping @ returns None without DB query."""
        cast(Any, handler).db.chatUsers = Mock()

        result = await handler._resolveUserId(chatId=-100123, username="@")

        assert result is None
        cast(Any, handler).db.chatUsers.getChatUserByUsername.assert_not_called()

    async def test_resolve_none(self, handler: ChatSearchHandler) -> None:
        """None username returns None without DB query."""
        cast(Any, handler).db.chatUsers = Mock()

        result = await handler._resolveUserId(chatId=-100123, username=None)

        assert result is None
        cast(Any, handler).db.chatUsers.getChatUserByUsername.assert_not_called()

    async def test_resolve_no_match(self, handler: ChatSearchHandler) -> None:
        """No DB match returns None."""
        cast(Any, handler).db.chatUsers = Mock()
        cast(Any, handler).db.chatUsers.getChatUserByUsername = AsyncMock(return_value=None)

        result = await handler._resolveUserId(chatId=-100123, username="nobody")

        assert result is None
        cast(Any, handler).db.chatUsers.getChatUserByUsername.assert_called_once_with(
            chatId=-100123, username="@nobody"
        )

    async def test_resolve_missing_user_id(self, handler: ChatSearchHandler) -> None:
        """DB row without user_id returns None."""
        cast(Any, handler).db.chatUsers = Mock()
        cast(Any, handler).db.chatUsers.getChatUserByUsername = AsyncMock(return_value={"username": "@testuser"})

        result = await handler._resolveUserId(chatId=-100123, username="testuser")

        assert result is None
        cast(Any, handler).db.chatUsers.getChatUserByUsername.assert_called_once_with(
            chatId=-100123, username="@testuser"
        )
