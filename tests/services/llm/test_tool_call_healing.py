"""Tests for LLM tool-call healing / recovery strategies in LLMService.

Covers:
- ``<tool_call>`` tag-wrapped JSON healing (``_matchTextForToolCallTags``).
- Broken-but-known tool-call fallback (``_matchTextForBrokenKnownToolCall``).
- The orchestrator (``_tryHealToolCall``) priority chain.
- End-to-end integration through ``generateTextViaLLM`` (broken -> retry ->
  final, and ``<tool_call>`` healing -> handler called -> final).
- Backward compatibility of the new ``LLMToolCall.errorMessage`` field
  (stays out of ``__str__`` / serialized output).

The real model-failure texts used below are taken verbatim from the repo-root
``failed*.jsonl`` captures that motivated this refactor.
"""

from typing import Any, Dict, List
from unittest.mock import Mock

import pytest

from internal.services.llm.service import LLMService
from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager
from lib.ai.models import LLMToolCall, ModelMessage, ModelResultStatus, ModelRunResult
from tests.utils import createAsyncMock

# ============================================================================
# Real failure captures (verbatim assistant ``response`` text).
# ============================================================================

# failed.2026-07-03.jsonl — unparseable Russian pseudo-call of a known tool,
# ending the message inside a bracket block.
FAILED_0703_TEXT: str = (
    " Понял, запускаю генерацию по вашему промту!\n\n"
    "[Вызов функции `generate_and_send_image` с промтом: «Средневековая миниатюра "
    "в стиле книжных иллюстраций XV века. Булочка\u202fIII."
    "Атмосфера благородного пятничного подвига»]"
)

# failed.2026-07-10.jsonl — same shape, longer preamble, the bracket block ends
# the message.
FAILED_0710_TEXT: str = (
    " Понял, сделаю открытку в стиле «упоротых» поздравлений!\n\n"
    "**Промт для генерации:**\n«Открытка в стиле „упоротых“ поздравлений "
    "безвкусно, но весело и празднично».\n\n"
    "[Вызов функции `generate_and_send_image` с указанным промтом]"
)

# failed-20260719.jsonl — article prose + a markdown link in the MIDDLE of the
# message, followed by a call-to-action and the broken bracket call mid-message
# (NOT at an edge), with a fenced JSON params block trailing it. The previous
# single-regex matcher anchored on the FIRST ``[`` (the markdown-link label)
# and never reached the actual broken-call bracket, so this capture was not
# healed. Verbatim assistant ``response`` (2707 chars).
FAILED_0719_TEXT: str = (
    " \n### Компания запустила спутники\n\n"
    "**Ключевые детали:**\n\n"
    "* Первоисточник: [Новостной сайт](https://news.ru/1/2/3"
    ")\n* Для проверки и углублённого изучения темы рекомендую также обратиться к "
    "следующим источникам:\n    * Официальные пресс‑релизы\n"
    "    * Научные базы данных и журналы: *arXiv.org* (препринты научных статей), *Nature* или "
    "**Визуализация:**\n\n"
    "Сейчас сгенерирую изображение для поста!\n\n"
    "[Вызов функции `generate_and_send_image`]\n\n"
    '```json\n{\n  "image_prompt": "Футуристическая иллюстрация: группа современных спутников на орбите Земли.'
    'В верхней части изображения надпись: «Компания запустила спутники»",\n  '
    '"image_description": "Иллюстрация для новостного поста о запуске спутников."\n}\n```'
)

# failed-20260716.jsonl — clean JSON inside <tool_call> tags (healable).
FAILED_0716_TEXT: str = (
    " Сейчас изучу статью и поищу дополнительные надёжные источники.\n\n"
    "**Шаг\xa01.** Сначала ознакомлюсь с содержанием исходной статьи по ссылке.\n\n"
    "<tool_call>\n"
    '{"name":"get_url_content","arguments":{"url":"https:\\/\\/news\\/1\\/2\\/'
    "3\\/4"
    '5\\/","parse_to_markdown":true}}\n'
    "</tool_call>"
)

# failed-20260719-v2.jsonl — article prose + source URLs + a fenced JSON code
# block at the END of the message (empty suffix) whose JSON uses ``"function"``
# KEY instead of ``"name"`` for the tool name. The ``_matchTextForJSONToolCall``
# matcher parses the JSON but then looks for ``jsonData.get("name", "")`` which
# returns ``""`` — causing ``_tryApplyToolCallMatch`` to reject the match.
# Anonymized from the real capture (real URLs, names, and prose replaced).
FAILED_0719V2_TEXT: str = (
    " Here's a news summary about a recent tech announcement involving"
    " a certificate authority revocation.\n\n"
    "**Key details:**\n\n"
    "* Source: [Tech News Site](https://example.com/news/1/2/3)\n"
    "* Additional sources for verification:\n"
    "    * Official press releases from the company\n"
    "    * Industry analysis and technical blogs\n"
    "    * Security community discussions\n\n"
    "---\n\n"
    "**Draft post for publication:**\n\n"
    "A major certificate authority has revoked SSL certificates for government"
    " domains, causing service outages.\n\n"
    "**Background:** Starting June 2026, the CA began mandatory revocation of"
    " certificates for Russian organizations due to new CA/Browser Forum"
    " requirements.\n\n"
    "Now generating an image for the post...\n\n"
    "[Generating image...]\n\n"
    '```\n{\n  "function": "generate_and_send_image",\n'
    '  "arguments": {\n'
    '    "image_prompt": "An illustration in digital art style depicting a'
    " penguin with glasses and a laptop sitting in front of a screen showing"
    " an SSL certificate error. Modern minimalist style with humorous"
    ' elements. 16:9 aspect ratio."\n'
    "  }\n"
    "}\n"
    "```"
)


# ============================================================================
# Fixtures (mirror tests/services/llm/test_llm_service.py).
# ============================================================================


@pytest.fixture
def llmService(mockLlmManager) -> LLMService:
    """Create a fresh LLMService instance for each test."""
    # The autouse resetLlmServiceSingleton in tests/conftest.py also clears the
    # singleton, but we set it explicitly for clarity / self-containment.
    LLMService._instance = None
    service = LLMService()
    service.injectLLMManager(mockLlmManager)
    return service


@pytest.fixture
def mockModel() -> Mock:
    """Create a mock AbstractModel."""
    model = Mock(spec=AbstractModel)
    model.modelId = "test-model"
    model.modelVersion = "1.0"
    model._customParams = {"temperature": 0.7}
    model.contextSize = 4096
    model.generateText = createAsyncMock()
    model.getEstimateTokensCount = Mock(return_value=100)
    return model


@pytest.fixture
def mockFallbackModel() -> Mock:
    """Create a mock fallback AbstractModel."""
    model = Mock(spec=AbstractModel)
    model.modelId = "fallback-model"
    model.modelVersion = "1.0"
    model._customParams = {"temperature": 0.7}
    model.contextSize = 4096
    model.generateText = createAsyncMock()
    model.getEstimateTokensCount = Mock(return_value=100)
    return model


@pytest.fixture
def mockChatSettings() -> Mock:
    """Create mock chat settings (supports __getitem__ with .toModel()/.toStr())."""
    settings = Mock()
    settings.__getitem__ = Mock(return_value=Mock(toModel=Mock(return_value=None)))
    return settings


@pytest.fixture
def mockLlmManager() -> Mock:
    """Create mock LLM manager."""
    return Mock(spec=LLMManager)


@pytest.fixture
def sampleMessages() -> List[ModelMessage]:
    """Create sample messages for testing."""
    return [
        ModelMessage(role="system", content="You are a helpful assistant"),
        ModelMessage(role="user", content="What is the weather?"),
    ]


# ============================================================================
# Tests
# ============================================================================


class TestToolCallHealing:
    """Cover the tool-call healing matchers, the orchestrator, and the error short-circuit."""

    # ------------------------------------------------------------------
    # 1. <tool_call> tag healing (direct matcher)
    # ------------------------------------------------------------------
    def testToolCallTagHealingDirect(self, llmService: LLMService) -> None:
        """``_matchTextForToolCallTags`` heals ``<tool_call>``-wrapped JSON into TOOL_CALLS."""
        llmService.registerTool("getWeather", "Get weather", [], _noopAsyncHandler)
        jsonPayload = '{"name":"getWeather","arguments":{"location":"Tokyo","units":"celsius"}}'
        resultText = "Let me check the weather.\n<tool_call>\n" + jsonPayload + "\n</tool_call>"
        ret = ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=resultText)

        matched = llmService._matchTextForToolCallTags(ret)

        assert matched is True
        assert ret.status == ModelResultStatus.TOOL_CALLS
        assert len(ret.toolCalls) == 1
        assert ret.toolCalls[0].name == "getWeather"
        assert ret.toolCalls[0].parameters == {"location": "Tokyo", "units": "celsius"}
        assert ret.toolCalls[0].errorMessage is None
        assert "<tool_call>" not in ret.resultText
        assert ret.resultText == "Let me check the weather."

    # ------------------------------------------------------------------
    # 2. <tool_call> healing via the orchestrator
    # ------------------------------------------------------------------
    def testToolCallTagHealingViaOrchestrator(self, llmService: LLMService) -> None:
        """``_tryHealToolCall`` reaches the ``<tool_call>`` tag matcher in priority order."""
        llmService.registerTool("getWeather", "Get weather", [], _noopAsyncHandler)
        jsonPayload = '{"name":"getWeather","arguments":{"location":"Tokyo","units":"celsius"}}'
        resultText = "Let me check the weather.\n<tool_call>\n" + jsonPayload + "\n</tool_call>"
        ret = ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=resultText)

        matched = llmService._tryHealToolCall(ret)

        assert matched is True
        assert ret.status == ModelResultStatus.TOOL_CALLS
        assert ret.toolCalls[0].name == "getWeather"
        assert ret.toolCalls[0].parameters == {"location": "Tokyo", "units": "celsius"}
        assert "<tool_call>" not in ret.resultText

    # ------------------------------------------------------------------
    # 3. Broken-known-tool bracket (direct) — real 07-03 text
    # ------------------------------------------------------------------
    def testBrokenKnownToolCallDirect0703(self, llmService: LLMService) -> None:
        """``_matchTextForBrokenKnownToolCall`` turns the real 07-03 pseudo-call into a retry error."""
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        ret = ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=FAILED_0703_TEXT)

        matched = llmService._matchTextForBrokenKnownToolCall(ret)

        assert matched is True
        assert ret.status == ModelResultStatus.TOOL_CALLS
        assert len(ret.toolCalls) == 1
        assert ret.toolCalls[0].name == "generate_and_send_image"
        assert ret.toolCalls[0].parameters == {}
        assert ret.toolCalls[0].errorMessage is not None
        assert "generate_and_send_image" in ret.toolCalls[0].errorMessage
        assert "retry" in ret.toolCalls[0].errorMessage
        # The original text is preserved (bracket content is no longer
        # stripped) so the model sees its full intent on retry.
        assert ret.resultText == FAILED_0703_TEXT.strip()
        assert "[" in ret.resultText

    # ------------------------------------------------------------------
    # 3b. Broken-known-tool bracket (direct) — real 07-10 text
    # ------------------------------------------------------------------
    def testBrokenKnownToolCallDirect0710(self, llmService: LLMService) -> None:
        """``_matchTextForBrokenKnownToolCall`` handles the real 07-10 pseudo-call identically."""
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        ret = ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=FAILED_0710_TEXT)

        matched = llmService._matchTextForBrokenKnownToolCall(ret)

        assert matched is True
        assert ret.status == ModelResultStatus.TOOL_CALLS
        assert ret.toolCalls[0].name == "generate_and_send_image"
        assert ret.toolCalls[0].parameters == {}
        assert ret.toolCalls[0].errorMessage is not None
        assert "retry" in ret.toolCalls[0].errorMessage
        # The original text is preserved (bracket content is no longer
        # stripped) so the model sees its full intent on retry.
        assert ret.resultText == FAILED_0710_TEXT.strip()
        assert "[" in ret.resultText

    # ------------------------------------------------------------------
    # 3c. Broken-known-tool bracket (direct) — real 07-19 text
    # ------------------------------------------------------------------
    def testBrokenKnownToolCallDirect0719(self, llmService: LLMService) -> None:
        """``_matchTextForBrokenKnownToolCall`` heals the real 07-19 mid-message pseudo-call.

        Unlike the 07-03 / 07-10 captures, the broken-call bracket here is NOT
        at an edge: it follows a long article preamble AND a markdown link
        (``[Новостной сайт](https://news.ru/...)``) that appears earlier in the
        text, and it is followed by a fenced JSON params block. The matcher
        must scan ALL ``[...]`` blocks (not just the first one) and accept the
        bracket because the entire suffix is a fenced JSON code block
        (`` ```json{...}``` ``) — matching ``hasJsonParams`` — so the
        broken-call candidate is accepted and converted to a ``TOOL_CALLS``
        retry-error.
        """
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        ret = ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=FAILED_0719_TEXT)

        matched = llmService._matchTextForBrokenKnownToolCall(ret)

        assert matched is True
        assert ret.status == ModelResultStatus.TOOL_CALLS
        assert len(ret.toolCalls) == 1
        assert ret.toolCalls[0].name == "generate_and_send_image"
        assert ret.toolCalls[0].parameters == {}
        assert ret.toolCalls[0].errorMessage is not None
        assert "broken call" in ret.toolCalls[0].errorMessage
        # The matched bracket block itself is preserved (not stripped) so the
        # model sees its full intent on retry.
        assert "[Вызов функции" in ret.resultText
        assert "`generate_and_send_image`" in ret.resultText
        # The article preamble (prefix) and the trailing fenced JSON
        # params block (suffix) are preserved. The two substrings below appear
        # ONLY inside the markdown-link label/URL, so they lock in that both
        # brackets are preserved verbatim; the markdown-link bracket was not
        # corrupted by the broken-call match.
        assert "Новостной сайт" in ret.resultText, "markdown link label must be preserved verbatim"
        assert "news.ru" in ret.resultText, "markdown link URL must be preserved verbatim"
        assert "image_prompt" in ret.resultText

    def testNotBrokenKnownToolCallInTheMiddle(self, llmService: LLMService) -> None:
        """``_matchTextForBrokenKnownToolCall`` test"""
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        ret = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Test1 [ generate_and_send_image ] Test2 [ `generate_and_send_image` ] Test3",
        )

        matched = llmService._matchTextForBrokenKnownToolCall(ret)

        assert matched is False
        assert ret.status == ModelResultStatus.FINAL
        assert len(ret.toolCalls) == 0
        assert "generate_and_send_image" in ret.resultText

    # ------------------------------------------------------------------
    # 3d. Broken-known-tool: mid-message bracket WITHOUT backticks is rejected
    # ------------------------------------------------------------------
    def testBrokenKnownToolCallMidMessageNoJsonSuffixRejected(self, llmService: LLMService) -> None:
        """A mid-message bracket naming a tool but WITHOUT backticks must NOT be healed.

        A bracket block that is not at an edge is only accepted when the
        entire suffix is a fenced JSON code block (``hasJsonParams``).
        The suffix ``" more prose."`` is not a JSON code block, so the
        matcher correctly returns ``False`` without changing the status.
        """
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        ret = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Some prose [use generate_and_send_image here] more prose.",
        )

        matched = llmService._matchTextForBrokenKnownToolCall(ret)

        assert matched is False
        assert ret.status == ModelResultStatus.FINAL
        assert ret.toolCalls == []

    # ------------------------------------------------------------------
    # 4. Broken-known-tool NO false positive on prose mention
    # ------------------------------------------------------------------
    def testBrokenKnownToolCallNoFalsePositiveProse(self, llmService: LLMService) -> None:
        """A mid-prose tool-name mention must not be healed."""
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        ret = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="I would use generate_and_send_image to make a picture of a cat.",
        )

        assert llmService._matchTextForBrokenKnownToolCall(ret) is False
        assert llmService._tryHealToolCall(ret) is False
        assert ret.status == ModelResultStatus.FINAL

    # ------------------------------------------------------------------
    # 5. Broken-known-tool with an unknown (unregistered) name
    # ------------------------------------------------------------------
    def testBrokenKnownToolCallUnknownName(self, llmService: LLMService) -> None:
        """A bracket block referencing an unregistered tool must not match."""
        ret = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="[Вызов функции `nonexistent_tool` с промтом: «что-то»]",
        )

        assert llmService._matchTextForBrokenKnownToolCall(ret) is False
        assert ret.status == ModelResultStatus.FINAL

    # ------------------------------------------------------------------
    # 5b. Broken-known-tool NO false positive on a mid-message markdown link
    # ------------------------------------------------------------------
    def testBrokenKnownToolCallNoFalsePositiveMidMessageLink(self, llmService: LLMService) -> None:
        """A mid-message markdown link ``[text](url)`` must not match: both edges are non-empty."""
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        ret = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="See [this article](https://example.com) for details.",
        )

        assert llmService._matchTextForBrokenKnownToolCall(ret) is False
        assert llmService._tryHealToolCall(ret) is False
        assert ret.status == ModelResultStatus.FINAL

    # ------------------------------------------------------------------
    # 5c. Broken-known-tool NO false positive on a trailing footnote
    # ------------------------------------------------------------------
    def testBrokenKnownToolCallNoFalsePositiveTrailingFootnote(self, llmService: LLMService) -> None:
        """A trailing footnote ``[1]`` must not match: ``"1"`` is not a registered tool name."""
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        ret = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="Some claim here.[1]",
        )

        assert llmService._matchTextForBrokenKnownToolCall(ret) is False
        assert llmService._tryHealToolCall(ret) is False
        assert ret.status == ModelResultStatus.FINAL

    # ------------------------------------------------------------------
    # 5d. Accepted false positive: trailing markdown link whose text is a tool name
    # ------------------------------------------------------------------
    def testBrokenKnownToolCallAcceptsTrailingMarkdownLink(self, llmService: LLMService) -> None:
        """A trailing ``[toolName](url)`` matches — an accepted trade-off of the heuristic.

        The bracket sits at the message edge (empty prefix) and its content
        word-boundary-matches a registered tool name, so
        ``_matchTextForBrokenKnownToolCall`` treats it as a broken-call candidate.
        Rejecting it cleanly would require demanding call-like markers (backticks /
        "function" / "вызов"), which risks under-matching the real broken-call
        failures (see the 07-03 / 07-10 captures). The handler is never executed
        for such a match — only a generic retry error is emitted — so the cost of
        the false positive is a single extra model round-trip.
        """
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        ret = ModelRunResult(
            rawResult={},
            status=ModelResultStatus.FINAL,
            resultText="[generate_and_send_image](https://docs.example.com)",
        )

        # Accepted false positive: matches and converts to a retry error.
        assert llmService._matchTextForBrokenKnownToolCall(ret) is True
        assert ret.status == ModelResultStatus.TOOL_CALLS
        assert len(ret.toolCalls) == 1
        assert ret.toolCalls[0].name == "generate_and_send_image"
        assert ret.toolCalls[0].errorMessage is not None
        assert "retry" in ret.toolCalls[0].errorMessage

    # ------------------------------------------------------------------
    # 6. Integration: broken -> retry -> final (handler never awaited)
    # ------------------------------------------------------------------
    async def testIntegrationBrokenKnownToolRetryThenFinal(
        self,
        llmService: LLMService,
        mockModel: Mock,
        mockFallbackModel: Mock,
        sampleMessages: List[ModelMessage],
        mockChatSettings: Mock,
    ) -> None:
        """A broken-known-tool call is fed back as a retry error; the handler is never called."""
        callLog: List[Dict[str, Any]] = []

        async def imageHandler(extraData: Any = None, **kwargs: Any) -> Dict[str, Any]:
            callLog.append(dict(kwargs))
            return {"done": True, "url": "https://example.com/img.png"}

        llmService.registerTool("generate_and_send_image", "Generate image", [], imageHandler)

        brokenResult = ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=FAILED_0703_TEXT)
        finalResult = ModelRunResult(
            rawResult={}, status=ModelResultStatus.FINAL, resultText="Готово, не получилось — попробуй иначе."
        )
        mockModel.generateText.side_effect = [brokenResult, finalResult]

        result = await llmService.generateTextViaLLM(
            messages=sampleMessages,
            chatId=None,
            chatSettings=mockChatSettings,
            modelKey=mockModel,
            fallbackModelKey=mockFallbackModel,
            useTools=True,
            extraData={},
        )

        # The handler was never executed (the error branch short-circuited it).
        assert callLog == []
        assert result.resultText == finalResult.resultText
        assert mockModel.generateText.call_count == 2

        # The second model call must include a role="tool" message carrying the
        # retry error — proving the broken call was fed back to the model.
        secondCallMessages: List[ModelMessage] = mockModel.generateText.call_args_list[1].args[0]
        toolMessages = [m for m in secondCallMessages if m.role == "tool"]
        assert len(toolMessages) == 1
        assert "retry" in toolMessages[0].content
        assert "generate_and_send_image" in toolMessages[0].content

    # ------------------------------------------------------------------
    # 7. Integration: <tool_call> healing -> handler called -> final
    # ------------------------------------------------------------------
    async def testIntegrationToolCallTagHealingThenHandlerCalled(
        self,
        llmService: LLMService,
        mockModel: Mock,
        mockFallbackModel: Mock,
        sampleMessages: List[ModelMessage],
        mockChatSettings: Mock,
    ) -> None:
        """A ``<tool_call>``-tagged response is healed, the handler is called with parsed args."""
        callLog: List[Dict[str, Any]] = []

        async def getUrlContent(extraData: Any = None, **kwargs: Any) -> Dict[str, Any]:
            callLog.append(dict(kwargs))
            return {"content": "fetched page"}

        llmService.registerTool("get_url_content", "Get URL content", [], getUrlContent)

        tagResult = ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=FAILED_0716_TEXT)
        finalResult = ModelRunResult(
            rawResult={}, status=ModelResultStatus.FINAL, resultText="Вот краткое содержание статьи."
        )
        mockModel.generateText.side_effect = [tagResult, finalResult]

        result = await llmService.generateTextViaLLM(
            messages=sampleMessages,
            chatId=None,
            chatSettings=mockChatSettings,
            modelKey=mockModel,
            fallbackModelKey=mockFallbackModel,
            useTools=True,
            extraData={},
        )

        # The handler was called exactly once with the arguments parsed out of
        # the ``<tool_call>`` JSON (note: ``\/`` escapes decode to ``/``).
        assert len(callLog) == 1
        assert callLog[0]["parse_to_markdown"] is True
        assert callLog[0]["url"].startswith("https://news/")
        assert result.resultText == finalResult.resultText
        assert mockModel.generateText.call_count == 2

    # ------------------------------------------------------------------
    # 8. ``"function"`` key support in ``_matchTextForJSONToolCall`` (07-19-v2)
    # ------------------------------------------------------------------
    def testJSONToolCallFunctionKeyDirect(self, llmService: LLMService) -> None:
        """``_matchTextForJSONToolCall`` extracts from a fenced JSON block using ``"function"`` instead of ``"name"``.

        The model emitted a fenced `` ```json{...}```  `` block at the very end
        of the response (empty suffix) with ``"function"`` key — not ``"name"``.
        The matcher should recognise it and convert to ``TOOL_CALLS``.
        """
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        ret = ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=FAILED_0719V2_TEXT)

        matched = llmService._matchTextForJSONToolCall(ret)

        assert matched is True
        assert ret.status == ModelResultStatus.TOOL_CALLS
        assert len(ret.toolCalls) == 1
        assert ret.toolCalls[0].name == "generate_and_send_image"
        # The JSON ``"arguments"`` dict survived, including the ``"image_prompt"`` key.
        assert "image_prompt" in ret.toolCalls[0].parameters
        assert ret.toolCalls[0].errorMessage is None
        # The fenced JSON block is stripped from resultText; preamble remains.
        assert "function" not in ret.resultText
        assert "Here's a news summary" in ret.resultText
        assert "Generating image" in ret.resultText

    def testJSONToolCallFunctionKeyViaOrchestrator(self, llmService: LLMService) -> None:
        """``_tryHealToolCall`` reaches ``_matchTextForJSONToolCall`` (priority 1) for ``"function"``-key JSON.

        The orchestrator tries the JSON-fence matcher first, so it should
        match before any other strategy.
        """
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        ret = ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=FAILED_0719V2_TEXT)

        matched = llmService._tryHealToolCall(ret)

        assert matched is True
        assert ret.status == ModelResultStatus.TOOL_CALLS
        assert ret.toolCalls[0].name == "generate_and_send_image"

    def testToolCallTagFunctionKeyDirect(self, llmService: LLMService) -> None:
        """``_matchTextForToolCallTags`` extracts from ``<tool_call>`` tags using ``"function"`` instead of ``"name"``.

        Same bug pattern: the JSON inside the tags uses ``"function"`` key.
        The matcher must fall back to ``"function"`` when ``"name"`` is absent.
        """
        llmService.registerTool("generate_and_send_image", "Generate image", [], _noopAsyncHandler)
        jsonPayload = '{"function":"generate_and_send_image","arguments":{"p":"v"}}'
        resultText = "Let me generate that.\n<tool_call>\n" + jsonPayload + "\n</tool_call>"
        ret = ModelRunResult(rawResult={}, status=ModelResultStatus.FINAL, resultText=resultText)

        matched = llmService._matchTextForToolCallTags(ret)

        assert matched is True
        assert ret.status == ModelResultStatus.TOOL_CALLS
        assert len(ret.toolCalls) == 1
        assert ret.toolCalls[0].name == "generate_and_send_image"
        assert ret.toolCalls[0].parameters == {"p": "v"}
        assert ret.toolCalls[0].errorMessage is None
        assert "<tool_call>" not in ret.resultText
        assert ret.resultText == "Let me generate that."

    # ------------------------------------------------------------------
    # 9. Backward compat: errorMessage is optional and stays out of __str__
    # ------------------------------------------------------------------
    def testLLMToolCallErrorMessageBackwardCompat(self) -> None:
        """A default ``errorMessage`` is None and does not leak into ``__str__``."""
        toolCall = LLMToolCall(id="x", name="y", parameters={})
        assert toolCall.errorMessage is None
        # Compact jsonDumps: sorted keys, separators (",", ":").
        assert str(toolCall) == '{"id":"x","name":"y","parameters":{}}'

        # And when explicitly set, it still does not appear in __str__.
        toolCallWithError = LLMToolCall(id="x", name="y", parameters={}, errorMessage="boom")
        assert toolCallWithError.errorMessage == "boom"
        assert str(toolCallWithError) == '{"id":"x","name":"y","parameters":{}}'
        assert "errorMessage" not in str(toolCallWithError)
        assert "boom" not in str(toolCallWithError)

    # ------------------------------------------------------------------
    # 10. processIntermediateMessages gate: broken-tool-call detection
    # ------------------------------------------------------------------
    def testProcessIntermediateMessagesGateDetectsBrokenToolCall(self) -> None:
        """The ``any(...)`` expression in the processIntermediateMessages gate correctly
        detects broken tool calls (``errorMessage`` is set).

        When ``processIntermediateMessages`` encounters a ``ModelRunResult``
        whose ``toolCalls`` list contains any entry with ``errorMessage`` set,
        it must RETURN early without calling ``sendMessage``. This test locks
        in that the detection expression — ``any(tc.errorMessage is not None
        for tc in toolCalls)`` — evaluates correctly for all meaningful
        combinations.
        """
        # A tool call with errorMessage set (broken-call retry) must be detected.
        brokenCall = LLMToolCall(id="1", name="test_tool", parameters={}, errorMessage="retry")
        assert any(tc.errorMessage is not None for tc in [brokenCall])

        # A tool call without errorMessage (normal call) must NOT be detected.
        cleanCall = LLMToolCall(id="2", name="test_tool", parameters={}, errorMessage=None)
        assert not any(tc.errorMessage is not None for tc in [cleanCall])

        # An empty toolCalls list must not trigger the gate.
        assert not any(tc.errorMessage is not None for tc in [])

        # Mixed: one broken call among clean ones — must detect.
        assert any(tc.errorMessage is not None for tc in [cleanCall, brokenCall])

        # Mixed: all clean — must not detect.
        assert not any(
            tc.errorMessage is not None
            for tc in [
                cleanCall,
                LLMToolCall(id="3", name="other_tool", parameters={}),
            ]
        )


# ============================================================================
# Module-level async helper used as a stand-in tool handler.
# ============================================================================


async def _noopAsyncHandler(extraData: Any = None, **kwargs: Any) -> str:
    """No-op async tool handler used as a stand-in registration target.

    Args:
        extraData: Extra data dict passed by the service.
        **kwargs: Tool parameters (ignored).

    Returns:
        A fixed placeholder string.
    """
    return "noop"
