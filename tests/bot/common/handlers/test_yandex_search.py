"""Regression tests for :class:`YandexSearchHandler` condensing-prompt behaviour.

Covers Phase 2 of the ``condensing_prompt`` tool-parameter feature
(`docs/archive/plans/condensing-prompt-tool-param.md`):

* :class:`TestNormalizeCondensingPrompt` — unit cases for the
  :meth:`YandexSearchHandler._normalizeCondensingPrompt` static helper
  (``None`` / empty / whitespace → ``None``; otherwise stripped).
* :class:`TestCondensingPrompt` — integration cases driving the real
  :meth:`YandexSearchHandler._llmToolGetUrlContent` with only leaf
  dependencies mocked. Verifies that a caller-supplied
  ``condensing_prompt`` reaches the condensing LLM call as the system
  message, that ``None``/empty/whitespace fall back to the per-chat
  ``DOCUMENT_CONDENSING_PROMPT`` default, that the condensed-cache key
  differentiates by prompt, and that a cache hit short-circuits before
  download / condense.
* :class:`TestWebSearchForwarding` — verifies the ``max_size`` +
  ``condensing_prompt`` forwarding fix in
  :meth:`YandexSearchHandler._llmToolWebSearch` (each per-page
  ``_llmToolGetUrlContent`` call receives both parameters).

All tests are wired through the project's ``asyncio_mode = "auto"``
configuration and the autouse singleton-reset fixtures in
``tests/conftest.py`` (``resetLlmServiceSingleton``,
``resetProxyServiceSingleton``). No real network, LLM, or database I/O
occurs: the Yandex search client, the two URL caches, ``_downloadUrl``,
``getChatSettings`` and ``llmService.generateText`` are stubbed at the
instance level.
"""

import datetime
from typing import Any, Dict, List, Optional, Tuple, cast
from unittest.mock import AsyncMock, Mock, patch

from internal.bot.common.handlers.yandex_search import YandexSearchHandler
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
from lib.ai import ModelMessage, ModelResultStatus, ModelRunResult
from lib.cache import JsonKeyGenerator
from lib.proxy import ProxyHelper, ProxyType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default ``max_size`` used by ``_llmToolGetUrlContent`` when omitted.
DEFAULT_MAX_SIZE = 10240

#: Large fake page body — well above ``DEFAULT_MAX_SIZE`` so the
#: condensing branch always triggers in the integration tests.
LARGE_CONTENT = "x" * 20000

#: The default document-condensing prompt carried by the chat-settings
#: stub; tests assert the fallback path uses this exact string.
DEFAULT_DOC_PROMPT = "DEFAULT DOC PROMPT"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _makeConfigManager(proxyConfig: Optional[Dict[str, Any]] = None) -> Mock:
    """Build a ``ConfigManager`` stub satisfying ``YandexSearchHandler.__init__``.

    ``BaseBotHandler.__init__`` reads ``getBotConfig()``; the
    ``YandexSearchHandler.__init__`` raises ``RuntimeError`` unless
    ``getYandexSearchConfig()["enabled"]`` is truthy and supplies the
    ``api-key`` / ``folder-id`` the ``YandexSearchClient`` constructor
    consumes. No ``proxy`` / ``use-proxy`` keys are present by default so the
    (reset) ``ProxyService`` resolves a type-NONE config without I/O.

    Args:
        proxyConfig: Optional proxy configuration dict. If provided, includes
            ``use-proxy`` and ``proxy`` sections in the yandex-search config.

    Returns:
        ``Mock`` exposing ``getBotConfig()`` and ``getYandexSearchConfig()``
        with deterministic return values.
    """
    cm = Mock()
    cm.getBotConfig = Mock(return_value={"token": "test", "owners": []})

    ysConfig = {
        "enabled": True,
        "api-key": "test-api-key",
        "folder-id": "test-folder-id",
        "defaults": {},
    }

    if proxyConfig:
        ysConfig["use-proxy"] = True
        ysConfig["proxy"] = proxyConfig

    cm.getYandexSearchConfig = Mock(return_value=ysConfig)
    return cm


def _makeDatabase() -> Mock:
    """Build a ``Database`` stub with the repository placeholders the handler touches.

    Returns:
        ``Mock`` whose ``chatSettings`` attribute is itself a ``Mock``;
        the handler's ``getChatSettings`` is overridden at the instance
        level in every test, so the repository is never actually reached.
    """
    db = Mock()
    db.chatSettings = Mock()
    return db


def _makeEnsuredMessage(
    *,
    chatId: int = 100,
    messageId: int = 42,
    userId: int = 7,
) -> EnsuredMessage:
    """Build a real :class:`EnsuredMessage` for ``_llmToolGetUrlContent``.

    The production path validates ``isinstance(ensuredMessage,
    EnsuredMessage)`` and reads ``ensuredMessage.recipient.id`` for the
    ``getChatSettings`` / ``generateText`` calls, so a genuine instance
    (not a ``Mock``) is required.

    Args:
        chatId: Recipient chat id (default 100).
        messageId: Originating message id (default 42).
        userId: Sender user id (default 7).

    Returns:
        A fully constructed :class:`EnsuredMessage`.
    """
    return EnsuredMessage(
        sender=MessageSender(id=userId, name="Alice", username=f"@user{userId}"),
        recipient=MessageRecipient(id=chatId, chatType=ChatType.PRIVATE),
        messageId=messageId,
        date=datetime.datetime(2026, 5, 5, 12, 0, 0, tzinfo=datetime.timezone.utc),
        messageText="get the page",
    )


def _makeChatSettings() -> ChatSettingsDict:
    """Build a complete chat-settings dict for the condensing branch.

    Production subscripts ``chatSettings[ChatSettingsKey.DOCUMENT_CONDENSING_PROMPT]``
    directly (no ``.get()``), so the dict must carry at minimum the three
    keys the condensing block reads: ``DOCUMENT_CONDENSING_PROMPT``
    (fallback prompt), ``CHAT_MODEL`` and ``CONDENSING_MODEL``
    (``generateText`` model keys). Values are wrapped in real
    :class:`ChatSettingsValue` objects so ``.toStr()`` works.

    Returns:
        A :class:`ChatSettingsDict` covering every key the handler reads
        during condensing.
    """
    return {
        ChatSettingsKey.DOCUMENT_CONDENSING_PROMPT: ChatSettingsValue(DEFAULT_DOC_PROMPT),
        ChatSettingsKey.CHAT_MODEL: ChatSettingsValue("dummy-chat-model"),
        ChatSettingsKey.CONDENSING_MODEL: ChatSettingsValue("dummy-condensing-model"),
    }


def _modelRunResult(resultText: str) -> ModelRunResult:
    """Build a :class:`ModelRunResult` with ``FINAL`` status and given text.

    Mirrors the helper in ``tests/bot/common/handlers/test_llm_messages.py``;
    the condensing block requires ``status == ModelResultStatus.FINAL``
    and a truthy ``resultText`` to adopt the condensed output and write
    it to the condensed cache.

    Args:
        resultText: The ``resultText`` the mocked LLM "returned".

    Returns:
        A ``ModelRunResult`` ready to be returned by the
        ``llmService.generateText`` stub.
    """
    return ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=resultText)


def _captureGenerate() -> Tuple[AsyncMock, List[Mock]]:
    """Build an ``llmService.generateText`` stub that captures its ``prompt`` kwarg.

    The condensing block calls ``generateText(prompt=..., ...)`` (keyword,
    not positional). The returned stub records the full kwargs of each
    invocation; the captured ``prompt`` is a ``list[ModelMessage]`` whose
    index 0 is the system message (carrying the effective condensing
    prompt) and index 1 the user message (carrying the page content).

    Returns:
        ``(generateMock, calls)`` where ``calls`` is a list of each
        ``call`` object appended on invocation, in call order.
    """
    calls: List[Mock] = []

    async def generate(*args: object, **kwargs: object) -> ModelRunResult:
        calls.append(Mock(_kwargs=kwargs))
        return _modelRunResult("condensed text")

    mock = AsyncMock(side_effect=generate)
    return mock, calls


def _capturedPrompt(calls: List[Mock], index: int = 0) -> List[ModelMessage]:
    """Extract the ``prompt`` kwarg from a captured ``generateText`` call.

    Args:
        calls: The ``calls`` list returned by :func:`_captureGenerate`.
        index: Which captured call to read (default 0, the first).

    Returns:
        The ``list[ModelMessage]`` passed as ``prompt=``.
    """
    return calls[index]._kwargs["prompt"]


def _newHandler() -> YandexSearchHandler:
    """Construct a :class:`YandexSearchHandler` with stubbed leaf dependencies.

    Wires the two URL caches (``urlContentCache`` / ``urlContentCondensedCache``)
    as ``AsyncMock`` instances so ``.get`` / ``.set`` are individually
    controllable per test, and overrides ``getChatSettings`` /
    ``sendMessage`` at the instance level. Tests further reassign
    ``_downloadUrl``, ``llmService.generateText`` and the cache mocks as
    needed.

    Returns:
        A constructed :class:`YandexSearchHandler` ready for stubbing.
    """
    handler = YandexSearchHandler(
        configManager=_makeConfigManager(),
        database=_makeDatabase(),
        botProvider=BotProvider.TELEGRAM,
    )

    # Both caches become AsyncMocks so each test controls .get/.set.
    handler.urlContentCache = AsyncMock()
    handler.urlContentCache.get = AsyncMock(return_value=None)
    handler.urlContentCache.set = AsyncMock(return_value=None)
    handler.urlContentCondensedCache = AsyncMock()
    handler.urlContentCondensedCache.get = AsyncMock(return_value=None)
    handler.urlContentCondensedCache.set = AsyncMock(return_value=None)

    # Instance-level chat-settings stub (handler layer returns
    # Dict[ChatSettingsKey, ChatSettingsValue]).
    cast(Any, handler).getChatSettings = AsyncMock(return_value=_makeChatSettings())

    # Avoid any real HTTP.
    cast(Any, handler)._downloadUrl = AsyncMock(
        return_value={"done": True, "content": LARGE_CONTENT, "contentType": "text/plain"}
    )

    return handler


# ---------------------------------------------------------------------------
# 1. _normalizeCondensingPrompt unit tests
# ---------------------------------------------------------------------------


class TestNormalizeCondensingPrompt:
    """Unit tests for the :meth:`YandexSearchHandler._normalizeCondensingPrompt` helper.

    The helper is a pure static method, so these cases exercise it
    directly without constructing the handler.
    """

    def test_normalize_none_returns_none(self) -> None:
        """``None`` input → ``None`` (use default)."""
        assert YandexSearchHandler._normalizeCondensingPrompt(None) is None

    def test_normalize_empty_returns_none(self) -> None:
        """Empty string → ``None``."""
        assert YandexSearchHandler._normalizeCondensingPrompt("") is None

    def test_normalize_whitespace_returns_none(self) -> None:
        """Whitespace-only string → ``None``."""
        assert YandexSearchHandler._normalizeCondensingPrompt("   \n\t  ") is None

    def test_normalize_strips_and_returns(self) -> None:
        """Non-empty string is stripped and returned."""
        assert YandexSearchHandler._normalizeCondensingPrompt("  extract the recipe  ") == "extract the recipe"

    def test_normalize_plain_returns_as_is(self) -> None:
        """Already-trimmed string is returned unchanged."""
        assert YandexSearchHandler._normalizeCondensingPrompt("extract the recipe") == "extract the recipe"


# ---------------------------------------------------------------------------
# 2. _llmToolGetUrlContent condensing-prompt integration tests
# ---------------------------------------------------------------------------


class TestCondensingPrompt:
    """Integration tests for ``condensing_prompt`` handling in ``_llmToolGetUrlContent``.

    Drives the real handler with the download / caches / LLM mocked at
    the instance level. The fake downloaded content (``LARGE_CONTENT``)
    is intentionally ``>= max_size`` so the condensing branch always
    triggers; its ``contentType`` is ``text/plain`` so the real
    ``html_to_markdown`` converter is not invoked.
    """

    def _wireGenerate(self, handler: YandexSearchHandler) -> List[Mock]:
        """Attach a capturing ``generateText`` stub and return the calls list.

        Args:
            handler: Handler under test.

        Returns:
            The ``calls`` list (see :func:`_captureGenerate`) for later
            prompt inspection.
        """
        generate, calls = _captureGenerate()
        cast(Any, handler).llmService.generateText = generate
        return calls

    async def test_custom_prompt_used_as_system_message(self) -> None:
        """A non-empty ``condensing_prompt`` is used verbatim as the LLM system message.

        The default ``DOCUMENT_CONDENSING_PROMPT`` must NOT be used when
        a custom prompt is supplied.
        """
        handler = _newHandler()
        em = _makeEnsuredMessage()
        calls = self._wireGenerate(handler)

        await handler._llmToolGetUrlContent(
            extraData={"ensuredMessage": em},
            url="http://example.com/a",
            condensing_prompt="EXTRACT ONLY RECIPE",
        )

        prompt = _capturedPrompt(calls)
        assert prompt[0].role == "system"
        # Custom prompt wins, not the per-chat default.
        assert prompt[0].content == "EXTRACT ONLY RECIPE"
        assert prompt[0].content != DEFAULT_DOC_PROMPT
        # User message carries the page content.
        assert prompt[1].role == "user"
        assert prompt[1].content == LARGE_CONTENT

        # Cache write path: the condensed result is stored under a key
        # whose condensing_prompt is the stripped custom prompt.
        cacheSet = cast(AsyncMock, handler.urlContentCondensedCache.set)
        cacheSet.assert_awaited_once()
        assert cacheSet.call_args.args[0]["condensing_prompt"] == "EXTRACT ONLY RECIPE"
        assert cacheSet.call_args.args[1] == "condensed text"

    async def test_default_prompt_used_when_none(self) -> None:
        """Omitted ``condensing_prompt`` falls back to the per-chat default."""
        handler = _newHandler()
        em = _makeEnsuredMessage()
        calls = self._wireGenerate(handler)

        await handler._llmToolGetUrlContent(
            extraData={"ensuredMessage": em},
            url="http://example.com/b",
        )

        prompt = _capturedPrompt(calls)
        assert prompt[0].content == DEFAULT_DOC_PROMPT

    async def test_default_prompt_used_when_empty(self) -> None:
        """Empty-string ``condensing_prompt`` falls back to the per-chat default."""
        handler = _newHandler()
        em = _makeEnsuredMessage()
        calls = self._wireGenerate(handler)

        await handler._llmToolGetUrlContent(
            extraData={"ensuredMessage": em},
            url="http://example.com/c",
            condensing_prompt="",
        )

        prompt = _capturedPrompt(calls)
        assert prompt[0].content == DEFAULT_DOC_PROMPT

    async def test_default_prompt_used_when_whitespace(self) -> None:
        """Whitespace-only ``condensing_prompt`` falls back to the per-chat default."""
        handler = _newHandler()
        em = _makeEnsuredMessage()
        calls = self._wireGenerate(handler)

        await handler._llmToolGetUrlContent(
            extraData={"ensuredMessage": em},
            url="http://example.com/d",
            condensing_prompt="   \n",
        )

        prompt = _capturedPrompt(calls)
        assert prompt[0].content == DEFAULT_DOC_PROMPT

    async def test_cache_key_includes_custom_prompt(self) -> None:
        """The condensed-cache key dict carries the normalized custom prompt.

        A custom call records the stripped prompt under
        ``condensing_prompt``; a default call records ``None``.
        """
        handler = _newHandler()
        em = _makeEnsuredMessage()
        self._wireGenerate(handler)  # generateText must be awaitable for the set path
        cacheGet = cast(AsyncMock, handler.urlContentCondensedCache.get)

        # Custom-prompt call.
        await handler._llmToolGetUrlContent(
            extraData={"ensuredMessage": em},
            url="http://example.com/e",
            condensing_prompt="  EXTRACT RECIPE  ",
        )
        customKey = cacheGet.call_args.args[0]
        assert customKey["condensing_prompt"] == "EXTRACT RECIPE"
        assert customKey["url"] == "http://example.com/e"
        assert customKey["max_size"] == DEFAULT_MAX_SIZE

        # Fresh handler for the default call (independent mock state).
        handler2 = _newHandler()
        em2 = _makeEnsuredMessage()
        self._wireGenerate(handler2)
        cacheGet2 = cast(AsyncMock, handler2.urlContentCondensedCache.get)
        await handler2._llmToolGetUrlContent(
            extraData={"ensuredMessage": em2},
            url="http://example.com/e",
        )
        defaultKey = cacheGet2.call_args.args[0]
        assert defaultKey["condensing_prompt"] is None
        assert defaultKey["url"] == "http://example.com/e"
        assert defaultKey["max_size"] == DEFAULT_MAX_SIZE

    async def test_cache_key_differs_for_different_prompts(self) -> None:
        """Distinct custom prompts produce distinct cache keys (and thus distinct digests).

        Captures the two key dicts handed to ``urlContentCondensedCache.get``
        and asserts they differ in the ``condensing_prompt`` field. To
        prove the differentiation actually reaches storage, also feeds
        the captured dicts through the real ``JsonKeyGenerator(hash=True)``
        and asserts the SHA-512 digests differ.
        """
        # Custom prompt A.
        handlerA = _newHandler()
        emA = _makeEnsuredMessage()
        self._wireGenerate(handlerA)
        await handlerA._llmToolGetUrlContent(
            extraData={"ensuredMessage": emA},
            url="http://example.com/f",
            condensing_prompt="recipe only",
        )
        keyA = cast(AsyncMock, handlerA.urlContentCondensedCache.get).call_args.args[0]

        # Custom prompt B (same url + max_size).
        handlerB = _newHandler()
        emB = _makeEnsuredMessage()
        self._wireGenerate(handlerB)
        await handlerB._llmToolGetUrlContent(
            extraData={"ensuredMessage": emB},
            url="http://example.com/f",
            condensing_prompt="finances only",
        )
        keyB = cast(AsyncMock, handlerB.urlContentCondensedCache.get).call_args.args[0]

        # Captured key dicts differ specifically in condensing_prompt.
        assert keyA["condensing_prompt"] == "recipe only"
        assert keyB["condensing_prompt"] == "finances only"
        assert keyA != keyB

        # And the real generator produces distinct 128-char SHA-512 digests.
        gen = JsonKeyGenerator[Dict[str, Any]](hash=True)
        digestA = gen.generateKey(keyA)
        digestB = gen.generateKey(keyB)
        assert digestA != digestB
        assert len(digestA) == 128
        assert len(digestB) == 128

    async def test_condensed_cache_hit_short_circuits(self) -> None:
        """A condensed-cache hit returns the cached value without download or condense.

        ``_downloadUrl`` and ``llmService.generateText`` must never be
        awaited; the cached string is returned verbatim.
        """
        handler = _newHandler()
        em = _makeEnsuredMessage()
        download = cast(AsyncMock, cast(Any, handler)._downloadUrl)
        generate, _calls = _captureGenerate()
        cast(Any, handler).llmService.generateText = generate

        # Pre-seed the condensed cache.
        handler.urlContentCondensedCache.get = AsyncMock(return_value="CACHED CONDENSED")

        result = await handler._llmToolGetUrlContent(
            extraData={"ensuredMessage": em},
            url="http://example.com/g",
            condensing_prompt="anything",
        )

        assert result == "CACHED CONDENSED"
        download.assert_not_awaited()
        generate.assert_not_awaited()

    async def test_content_below_max_size_does_not_condense(self) -> None:
        """Content shorter than ``max_size`` skips the condensing branch entirely.

        With downloaded content well below the default ``max_size``
        (``10240``), neither the condensing LLM call nor the condensed-cache
        write is reached; the raw content is returned unchanged.
        """
        handler = _newHandler()
        em = _makeEnsuredMessage()
        generate, _calls = _captureGenerate()
        cast(Any, handler).llmService.generateText = generate
        # Override the default LARGE_CONTENT download with a short body.
        cast(Any, handler)._downloadUrl = AsyncMock(
            return_value={"done": True, "content": "x" * 100, "contentType": "text/plain"}
        )
        cacheSet = cast(AsyncMock, handler.urlContentCondensedCache.set)

        result = await handler._llmToolGetUrlContent(
            extraData={"ensuredMessage": em},
            url="http://example.com/short",
        )

        assert result == "x" * 100
        generate.assert_not_awaited()
        cacheSet.assert_not_awaited()


# ---------------------------------------------------------------------------
# 3. _llmToolWebSearch forwarding tests
# ---------------------------------------------------------------------------


class TestWebSearchForwarding:
    """Tests for the ``max_size`` + ``condensing_prompt`` forwarding fix in ``_llmToolWebSearch``.

    The per-page ``_llmToolGetUrlContent`` call inside the inner
    ``fetchUrlContent`` closure must receive both forwarded parameters,
    closing the pre-existing gap where ``web_search`` silently used the
    ``10240`` default and dropped any condensing prompt.
    """

    @staticmethod
    def _fakeSearchResult() -> Dict[str, Any]:
        """Build a minimal ``search`` result with one group / one doc.

        ``_llmToolWebSearch`` iterates ``searchResult["groups"]`` and, for
        each ``doc``, reads ``doc["url"]``, ``doc.get("extendedText", "")``
        and ``doc["passages"]`` (joined). One doc with a URL is enough to
        reach the per-page fetch.

        Returns:
            A ``SearchResponse``-shaped dict with a single one-doc group.
        """
        return {
            "groups": [
                [
                    {
                        "url": "http://example.com/page",
                        "extendedText": "ext",
                        "passages": ["snippet"],
                    }
                ]
            ]
        }

    def _wireWebSearchHandler(self) -> YandexSearchHandler:
        """Build a fresh handler with the search client and per-page fetch stubbed.

        Constructs its own handler via :func:`_newHandler`, then overrides
        ``yandexSearchClient.search`` to return a one-doc fake result and
        ``_llmToolGetUrlContent`` to return a short page string, so the
        ``_llmToolWebSearch`` forwarding logic runs in isolation.

        Returns:
            The handler with ``yandexSearchClient.search`` returning a
            one-doc fake result and ``_llmToolGetUrlContent`` as an
            awaitable ``AsyncMock`` returning a short page string.
        """
        handler = _newHandler()
        cast(Any, handler).yandexSearchClient = Mock()
        cast(Any, handler).yandexSearchClient.search = AsyncMock(return_value=self._fakeSearchResult())
        cast(Any, handler)._llmToolGetUrlContent = AsyncMock(return_value="page body")
        return handler

    async def test_web_search_forwards_condensing_prompt_and_max_size(self) -> None:
        """``web_search`` forwards both ``condensing_prompt`` and ``max_size`` to per-page fetch."""
        handler = self._wireWebSearchHandler()
        em = _makeEnsuredMessage()
        getUrl = cast(AsyncMock, cast(Any, handler)._llmToolGetUrlContent)

        await handler._llmToolWebSearch(
            extraData={"ensuredMessage": em},
            query="recipe",
            return_page_content=True,
            condensing_prompt="CUSTOM",
            max_size=500,
        )

        getUrl.assert_awaited_once()
        assert getUrl.call_args.kwargs["condensing_prompt"] == "CUSTOM"
        assert getUrl.call_args.kwargs["max_size"] == 500
        # Forwarded url + parse_to_markdown are unchanged in shape.
        assert getUrl.call_args.kwargs["url"] == "http://example.com/page"
        assert getUrl.call_args.kwargs["parse_to_markdown"] is True

    async def test_web_search_defaults_when_params_omitted(self) -> None:
        """Omitted params forward as the defaults (``None`` prompt, ``10240`` size)."""
        handler = self._wireWebSearchHandler()
        em = _makeEnsuredMessage()
        getUrl = cast(AsyncMock, cast(Any, handler)._llmToolGetUrlContent)

        await handler._llmToolWebSearch(
            extraData={"ensuredMessage": em},
            query="recipe",
            return_page_content=True,
        )

        getUrl.assert_awaited_once()
        assert getUrl.call_args.kwargs["condensing_prompt"] is None
        assert getUrl.call_args.kwargs["max_size"] == DEFAULT_MAX_SIZE


class TestHttp2EnabledForAllProxyTypes:
    """Regression test for HTTP/2 being enabled for ALL proxy types.

    HTTP/2 is negotiated via TLS ALPN entirely above the SOCKS5 tunnel — there
    is NO protocol incompatibility. httpcore2's native SOCKS path supports HTTP/2
    by construction, and ALPN degrades gracefully to HTTP/1.1 if the target
    server lacks h2 support. The old restriction (disabling HTTP/2 for SOCKS5)
    was an artifact of the retired third-party `httpx-socks` transport, which
    did not propagate client-level `http2=True` into a user-supplied transport.

    This test locks in the corrected behavior: HTTP/2 is enabled for ALL proxy
    types (SOCKS5, HTTP, NONE).
    """

    async def test_http2_enabled_when_proxy_type_is_socks5(self) -> None:
        """When proxy type is SOCKS5, http2 parameter passed to AsyncClient must be True.

        HTTP/2 is negotiated via TLS ALPN above the SOCKS5 tunnel; httpcore2
        supports it natively. The old httpx-socks-era restriction was removed
        after source+web research established h2-over-SOCKS was never a protocol
        limitation.

        Args:
            None
        """
        # Set SOCKS5 proxy BEFORE creating handler so handler.__init__ picks it up
        ProxyHelper.getInstance().setGlobalProxyConfig(
            {"enabled": True, "type": ProxyType.SOCKS5, "address": "socks5://proxy:1080"}
        )

        # Configure handler - will pick up SOCKS5 config from yandex-search proxy section
        handler = YandexSearchHandler(
            configManager=_makeConfigManager(proxyConfig={"type": ProxyType.SOCKS5, "address": "socks5://proxy:1080"}),
            database=_makeDatabase(),
            botProvider=BotProvider.TELEGRAM,
        )

        # Mock httpx.AsyncClient to capture the http2 parameter
        clientMock = AsyncMock()
        clientMock.__aenter__ = AsyncMock(return_value=clientMock)
        clientMock.__aexit__ = AsyncMock(return_value=None)
        clientMock.get = AsyncMock(
            return_value=Mock(
                status_code=200,
                headers={"content-type": "text/html"},
                content=b"<html>test</html>",
            )
        )

        with patch("httpx2.AsyncClient", return_value=clientMock) as mockClient:
            try:
                await handler._downloadUrl("http://example.com")
            except Exception:
                pass  # We only care about the AsyncClient call

            # Assert AsyncClient was called with http2=True
            mockClient.assert_called_once()
            assert mockClient.call_args.kwargs["http2"] is True, "HTTP/2 must be enabled when proxy type is SOCKS5"

    async def test_http2_enabled_when_proxy_type_is_http(self) -> None:
        """When proxy type is HTTP, http2 parameter passed to AsyncClient must be True.

        Args:
            None
        """
        # Set HTTP proxy BEFORE creating handler
        ProxyHelper.getInstance().setGlobalProxyConfig(
            {"enabled": True, "type": ProxyType.HTTP, "address": "http://proxy:8080"}
        )

        # Configure handler - will pick up HTTP config from yandex-search proxy section
        handler = YandexSearchHandler(
            configManager=_makeConfigManager(proxyConfig={"type": ProxyType.HTTP, "address": "http://proxy:8080"}),
            database=_makeDatabase(),
            botProvider=BotProvider.TELEGRAM,
        )

        # Mock httpx.AsyncClient to capture the http2 parameter
        clientMock = AsyncMock()
        clientMock.__aenter__ = AsyncMock(return_value=clientMock)
        clientMock.__aexit__ = AsyncMock(return_value=None)
        clientMock.get = AsyncMock(
            return_value=Mock(
                status_code=200,
                headers={"content-type": "text/html"},
                content=b"<html>test</html>",
            )
        )

        with patch("httpx2.AsyncClient", return_value=clientMock) as mockClient:
            try:
                await handler._downloadUrl("http://example.com")
            except Exception:
                pass  # We only care about the AsyncClient call

            # Assert AsyncClient was called with http2=True
            mockClient.assert_called_once()
            assert mockClient.call_args.kwargs["http2"] is True, "HTTP/2 must be enabled when proxy type is HTTP"

    async def test_http2_enabled_when_proxy_type_is_none(self) -> None:
        """When proxy type is NONE, http2 parameter passed to AsyncClient must be True.

        Args:
            None
        """
        # Set NONE proxy BEFORE creating handler
        ProxyHelper.getInstance().setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})

        # Configure handler with no proxy (NONE)
        handler = YandexSearchHandler(
            configManager=_makeConfigManager(),
            database=_makeDatabase(),
            botProvider=BotProvider.TELEGRAM,
        )

        # Mock httpx.AsyncClient to capture the http2 parameter
        clientMock = AsyncMock()
        clientMock.__aenter__ = AsyncMock(return_value=clientMock)
        clientMock.__aexit__ = AsyncMock(return_value=None)
        clientMock.get = AsyncMock(
            return_value=Mock(
                status_code=200,
                headers={"content-type": "text/html"},
                content=b"<html>test</html>",
            )
        )

        with patch("httpx2.AsyncClient", return_value=clientMock) as mockClient:
            try:
                await handler._downloadUrl("http://example.com")
            except Exception:
                pass  # We only care about the AsyncClient call

            # Assert AsyncClient was called with http2=True
            mockClient.assert_called_once()
            assert mockClient.call_args.kwargs["http2"] is True, "HTTP/2 must be enabled when proxy type is NONE"
