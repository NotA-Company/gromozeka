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
    "в стиле книжных иллюстраций XV века. Булочка\u202fIII — рыцарь Пятничного Ордена: "
    "кошка породы японский бобтейл в изящных серебристо‑золотых доспехах, украшенных "
    "хмельными шишками и пивными кружками. В лапе — меч с рукоятью в виде пробки от "
    "бутылки. На заднем плане — замок с флагами, на которых изображены кружки пива и "
    "коты. Фон — стилизованные облака и золотые завитки. Яркие локальные цвета, чёткие "
    "контуры, декоративные элементы по краям изображения, имитация пергамента. "
    "Атмосфера благородного пятничного подвига»]"
)

# failed.2026-07-10.jsonl — same shape, longer preamble, the bracket block ends
# the message.
FAILED_0710_TEXT: str = (
    " Понял, сделаю открытку в стиле «упоротых» поздравлений — с пивком и милыми "
    "мелочами!\n\n**Промт для генерации:**\n«Открытка в стиле „упоротых“ поздравлений "
    "из соцсетей: яркий, перегруженный деталями дизайн, как в гифках от возрастных "
    "пользователей. В центре — большая пенная кружка пива с улыбающейся мордочкой "
    "(глаза, улыбка). Вокруг — хаотично разбросанные милые и нелепые элементы: "
    "сердечки, звёздочки, блёстки, маленькие котики в солнечных очках, воздушные "
    "шары, конфетти, радуга, пара танцующих грибов, наклейка „Ура!“ с восклицательным "
    "знаком. По краям — виньетки с цветочками и ленточками. Фон — пастельно‑розовый "
    "с градиентом к голубому, украшен мелкими повторяющимися узорами (сердечки, "
    "пузырьки). Внизу крупная надпись игривым шрифтом: „С Пятничкой! 🍻✨“ — с "
    "тенями и бликами, как в дешёвом графическом редакторе. Всё выглядит нарочито "
    "безвкусно, но весело и празднично».\n\n"
    "[Вызов функции `generate_and_send_image` с указанным промтом]"
)

# failed-20260716.jsonl — clean JSON inside <tool_call> tags (healable).
FAILED_0716_TEXT: str = (
    " Сейчас изучу статью и поищу дополнительные надёжные источники.\n\n"
    "**Шаг\xa01.** Сначала ознакомлюсь с содержанием исходной статьи по ссылке.\n\n"
    "<tool_call>\n"
    '{"name":"get_url_content","arguments":{"url":"https:\\/\\/rus.lsm.lv\\/statja\\/novosti\\/'
    "ekonomika\\/13.07.2026-za-26-millionov-evro-latvijas-valsts-mezi-pokupaet-u-svedov-"
    'lesa-v-latgalii.a654851\\/","parse_to_markdown":true}}\n'
    "</tool_call>"
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
    model.temperature = 0.7
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
    model.temperature = 0.7
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


def _expectedPreamble(text: str) -> str:
    """Compute the preamble the healers should leave after stripping the bracket block.

    Args:
        text: The original model response text.

    Returns:
        The text up to the first ``[`` (the bracket block), stripped of
        surrounding whitespace — matching what ``_matchTextForBrokenKnownToolCall``
        assigns to ``resultText``.
    """
    return text.strip().split("[")[0].strip()


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
        # The bracket block is stripped, leaving the preamble.
        assert ret.resultText == _expectedPreamble(FAILED_0703_TEXT)
        assert "[" not in ret.resultText

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
        assert ret.resultText == _expectedPreamble(FAILED_0710_TEXT)
        assert "[" not in ret.resultText

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
        assert callLog[0]["url"].startswith("https://rus.lsm.lv/")
        assert result.resultText == finalResult.resultText
        assert mockModel.generateText.call_count == 2

    # ------------------------------------------------------------------
    # 8. Backward compat: errorMessage is optional and stays out of __str__
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
