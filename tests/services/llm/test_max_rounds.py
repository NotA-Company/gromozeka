"""Tests for the ``maxRounds`` round-limit in :meth:`LLMService.generateTextViaLLM`.

Covers the budget-exhaustion behaviour that bounds the tool-calling loop:
once ``roundN >= maxRounds`` the service must (a) stop offering tool
schemas, (b) clear the ``filteredToolNames`` execution allowlist so that
even healed tool calls cannot execute, (c) inject a steering directive
asking the model for a final answer, (d) disable tool-call healing, and
(e) force the loop to terminate within one additional round regardless of
what the model returns next.

Headline regressions:

- :func:`testMaxRoundsClosesHealingBypass`: under the old ``tools=[]``-only
  logic, ``filteredToolNames`` stayed populated, so a healed tool call still
  executed its handler after the budget was supposedly exhausted. Healing is
  now also gated off post-budget, so a healable FINAL text is never converted
  to TOOL_CALLS and cannot execute.
- :func:`testMaxRoundsTerminatesWhenModelKeepsReturningToolCallsPostBudget`:
  a glitching/loose provider that keeps emitting native ``TOOL_CALLS``
  despite the empty ``tools=[]`` previously re-iterated forever (appending
  "tool not available" results each round). The post-budget ``TOOL_CALLS``
  now falls through to ``else: break`` and a fallback answer is synthesized.
"""

import logging
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import AsyncMock, Mock

import pytest

from internal.services.llm.service import LLMService
from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager
from lib.ai.models import LLMToolCall, ModelMessage, ModelResultStatus, ModelRunResult
from tests.utils import createAsyncMock

# Steering text injected into the messages on budget exhaustion; must match
# the literal in ``internal/services/llm/service.py``.
STEERING_TEXT: str = (
    "You have reached the maximum number of tool-use rounds."
    " Stop calling tools and provide your final answer to the user now,"
    " using only the information you have already gathered."
)

POST_BUDGET_FALLBACK_TEXT: str = (
    "I've reached the limit of tool-use steps for this request;"
    " here is my best answer with the information gathered so far."
)
"""Fallback text synthesized on a post-budget break with no model text.

Must match the literal in ``internal/services/llm/service.py`` (the
``else:`` branch of the loop in ``generateTextViaLLM``)."""

DUMMY_TOOL_NAME: str = "dummy_tool"
"""Name of the single tool registered by these tests' harness."""


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def llmService() -> LLMService:
    """Create a fresh LLMService instance with a mock LLMManager injected.

    Relies on the autouse ``resetLlmServiceSingleton`` fixture from
    ``tests/conftest.py`` to clear the singleton before and after each test.

    Returns:
        A fresh LLMService with no registered tools.
    """
    service = LLMService.getInstance()
    service.injectLLMManager(Mock(spec=LLMManager))
    return service


@pytest.fixture
def mockModel() -> Mock:
    """Create a mock AbstractModel used as the resolved primary/fallback model.

    ``contextSize`` is read by ``generateTextViaLLM`` to compute the condense
    ``maxTokens`` budget; the value is otherwise unused because
    ``condenseContext`` is mocked out per-test.

    Returns:
        A ``Mock(spec=AbstractModel)`` with ``contextSize = 4096``.
    """
    model = Mock(spec=AbstractModel)
    model.contextSize = 4096
    return model


@pytest.fixture
def mockChatSettings() -> Mock:
    """Create mock chat settings supporting ``__getitem__`` lookups.

    ``generateTextViaLLM`` resolves the condensing prompt/model via
    ``chatSettings[Key].toStr()/.toModel()`` before the loop; those values are
    only consumed by the mocked ``condenseContext``, so generic Mock children
    suffice. Model keys passed as ``AbstractModel`` instances are returned
    directly by ``resolveModel`` (isinstance check), bypassing this lookup.

    Returns:
        A ``Mock`` whose ``__getitem__`` returns a generic ``Mock``.
    """
    settings = Mock()
    settings.__getitem__ = Mock(return_value=Mock())
    return settings


# ============================================================================
# Helpers
# ============================================================================


def _wireMocks(
    service: LLMService,
    *,
    generateSideEffects: List[ModelRunResult],
) -> AsyncMock:
    """Mock ``condenseContext`` (passthrough) and ``generateText`` on the service.

    ``condenseContext`` returns its input messages unchanged (plus an empty
    coverage dict) so the test controls the exact message sequence reaching
    ``generateText``. ``generateText`` returns the scripted
    :class:`ModelRunResult` objects in order, one per call.

    Args:
        service: The LLMService instance to wire mocks onto.
        generateSideEffects: Ordered list of results returned by successive
            ``generateText`` calls.

    Returns:
        The ``generateText`` AsyncMock (for call-count / call-args assertions).
    """

    def _condensePassthrough(messages: Sequence[ModelMessage], *_args: Any, **_kwargs: Any) -> tuple:
        """Return messages unchanged with empty coverage (condenseContext passthrough).

        Args:
            messages: The message sequence passed in positionally.
            *_args: Unused positional args (model, etc.) — genuine passthrough.
            **_kwargs: Unused keyword args (keepFirstN, maxTokens, etc.) —
                genuine passthrough.

        Returns:
            The ``(messages, {})`` tuple condenseContext is expected to yield.
        """
        return (messages, {})

    service.condenseContext = createAsyncMock(sideEffect=_condensePassthrough)
    generateTextMock = createAsyncMock()
    # Set side_effect directly (AsyncMock accepts a list) rather than via the
    # createAsyncMock helper, whose ``sideEffect`` param is typed as a Callable.
    generateTextMock.side_effect = generateSideEffects
    service.generateText = generateTextMock
    return generateTextMock


def _makeToolCallResult(callId: str = "call_1") -> ModelRunResult:
    """Build a native TOOL_CALLS result invoking the dummy tool.

    Args:
        callId: The tool-call id to assign.

    Returns:
        A ``ModelRunResult`` with ``TOOL_CALLS`` status and a single
        ``dummy_tool`` call carrying no parameters.
    """
    return ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id=callId, name=DUMMY_TOOL_NAME, parameters={})],
    )


def _makeFinalResult(text: str = "final answer") -> ModelRunResult:
    """Build a FINAL result with the given text.

    Args:
        text: The result text (non-empty so healing is attempted).

    Returns:
        A ``ModelRunResult`` with ``FINAL`` status and the supplied text.
    """
    return ModelRunResult(
        rawResult={},
        status=ModelResultStatus.FINAL,
        resultText=text,
    )


def _makeStatusResult(status: ModelResultStatus, text: str = "") -> ModelRunResult:
    """Build a result with an arbitrary status and text.

    Used to script error / content-filter responses that must propagate
    post-budget rather than be masked into a FINAL fallback.

    Args:
        status: The ``ModelResultStatus`` to assign.
        text: The result text (default empty — the realistic shape for an
            error / filtered response).

    Returns:
        A ``ModelRunResult`` with the requested status and text.
    """
    return ModelRunResult(
        rawResult={},
        status=status,
        resultText=text,
    )


def _toolNamesAtCall(generateTextMock: AsyncMock, callIndex: int) -> set:
    """Return the set of tool names offered at a given generateText call.

    Args:
        generateTextMock: The mocked ``generateText`` (with a call history).
        callIndex: Zero-based index into ``call_args_list``.

    Returns:
        A set of tool-name strings offered in that call (empty if no tools).
    """
    tools = generateTextMock.call_args_list[callIndex].kwargs["tools"]
    return {tool.name for tool in tools}


def _messagesAtCall(generateTextMock: AsyncMock, callIndex: int) -> List[ModelMessage]:
    """Return the messages list passed to generateText at a given call.

    Args:
        generateTextMock: The mocked ``generateText`` (with a call history).
        callIndex: Zero-based index into ``call_args_list``.

    Returns:
        The list of ModelMessage objects passed positionally to that call.
    """
    return generateTextMock.call_args_list[callIndex].args[0]


def _registerDummyTool(service: LLMService, callLog: List[Dict[str, Any]]) -> None:
    """Register a dummy tool whose handler records each invocation into callLog.

    Args:
        service: The LLMService instance to register the tool on.
        callLog: A list the handler appends a dict to on every call, so tests
            can assert on execution count / timing.

    Returns:
        None
    """

    async def dummyHandler(extraData: Optional[Dict[str, object]] = None, **kwargs: Any) -> str:
        """Record-then-return handler for the dummy tool.

        Args:
            extraData: Extra data dict passed by the service (unused).
            **kwargs: Tool parameters (unused).

        Returns:
            The string ``"ok"``.
        """
        callLog.append(dict(kwargs))
        return "ok"

    service.registerTool(DUMMY_TOOL_NAME, "dummy tool for maxRounds tests", [], dummyHandler)


# ============================================================================
# Tests
# ============================================================================


async def testMaxRoundsDropsToolsWhenBudgetExhausted(
    llmService: LLMService, mockModel: Mock, mockChatSettings: Mock
) -> None:
    """On/after budget exhaustion, generateText is called with an empty tools list.

    With ``maxRounds=2`` the first two calls keep the original tool offered
    (and executable), while the third call (roundN has reached 2) is made with
    ``tools == []``.
    """
    handlerCalls: List[Dict[str, Any]] = []
    _registerDummyTool(llmService, handlerCalls)
    generateTextMock = _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult("call_1"),
            _makeToolCallResult("call_2"),
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData={},
        maxRounds=2,
    )

    # Rounds 0 and 1 (calls 0, 1) keep the tool offered and executable.
    assert _toolNamesAtCall(generateTextMock, 0) == {DUMMY_TOOL_NAME}
    assert _toolNamesAtCall(generateTextMock, 1) == {DUMMY_TOOL_NAME}
    assert len(handlerCalls) == 2

    # Round 2 (call 2) has the budget exhausted -> no tools offered.
    assert _toolNamesAtCall(generateTextMock, 2) == set()
    assert generateTextMock.call_count == 3


async def testMaxRoundsClosesHealingBypass(llmService: LLMService, mockModel: Mock, mockChatSettings: Mock) -> None:
    """After budget exhaustion a healed tool call does NOT execute its handler.

    THE KEY REGRESSION TEST. Setup (``maxRounds=1``):

    - Call 0 (roundN=0, not exhausted): a native TOOL_CALLS -> handler runs.
    - Call 1 (roundN=1, exhausted): FINAL text shaped like a JSON code-fence
      tool call that ``_tryHealToolCall`` WOULD convert to TOOL_CALLS. Under
      the OLD logic healing ran unconditionally -> the converted call hit the
      execution branch; with ``filteredToolNames`` still populated (the
      pre-bypass bug) the handler ran again -> ``len(handlerCalls)`` would be
      2 and this test would FAIL. The fix gates healing on
      ``not budgetExhausted``: post-budget the healable text is NOT converted
      at all, so it can never become a tool call and the handler cannot run.

    Asserts the handler ran exactly once (only on the pre-budget call), the
    loop terminates on the exhausted round (does not re-iterate), and the
    (un-healed) text is returned as-is.
    """
    handlerCalls: List[Dict[str, Any]] = []
    _registerDummyTool(llmService, handlerCalls)

    # A fenced ```json {...} ``` block that _matchTextForJSONToolCall heals.
    healableFinalText: str = '```json\n{"name":"dummy_tool","arguments":{}}\n```'

    generateTextMock = _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult("call_1"),  # round 0: real call, handler runs
            _makeFinalResult(healableFinalText),  # round 1: exhausted -> heal skipped -> break
        ],
    )

    result = await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData={},
        maxRounds=1,
    )

    # Handler executed exactly once (the pre-budget native call). Post-budget
    # the healable text is never healed, so it never becomes an executable
    # tool call. Under the old bypass logic this would be 2.
    assert len(handlerCalls) == 1
    # The loop terminates on the exhausted round with the un-healed text as-is
    # (no third round), proving healing did not re-arm execution.
    assert result.resultText == healableFinalText
    assert generateTextMock.call_count == 2


async def testMaxRoundsInjectsSteeringMessage(llmService: LLMService, mockModel: Mock, mockChatSettings: Mock) -> None:
    """Post-budget the steering directive is folded into the leading system message.

    Provider-safety (MINOR 1): the directive must reach the model without
    introducing a mid-stream ``role="system"`` message, which the YC SDK
    provider historically rejects/ignores. When a leading system message is
    present (the realistic case — chats always carry a personality prompt) the
    directive is appended to it, keeping a single leading system message. With
    ``maxRounds=1``, call 0 is pre-budget (no steering) and call 1 is
    post-budget (steering folded into the leading system message).
    """
    handlerCalls: List[Dict[str, Any]] = []
    _registerDummyTool(llmService, handlerCalls)
    generateTextMock = _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult("call_1"),
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        messages=[
            ModelMessage(role="system", content="You are a helpful assistant."),
            ModelMessage(role="user", content="hi"),
        ],
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData={},
        maxRounds=1,
    )

    # Pre-budget call: no steering text anywhere.
    preBudgetMessages = _messagesAtCall(generateTextMock, 0)
    assert not any(STEERING_TEXT in (m.content or "") for m in preBudgetMessages)

    # Post-budget call: steering text is folded into the single leading system
    # message (not appended as a separate mid-stream message).
    postBudgetMessages = _messagesAtCall(generateTextMock, 1)
    steeringMessages = [m for m in postBudgetMessages if STEERING_TEXT in (m.content or "")]
    assert len(steeringMessages) == 1
    assert steeringMessages[0].role == "system"
    assert steeringMessages[0].content.startswith("You are a helpful assistant.")


async def testMaxRoundsNoneIsUnlimited(llmService: LLMService, mockModel: Mock, mockChatSettings: Mock) -> None:
    """``maxRounds=None`` disables the limit: tools are never emptied.

    The model returns TOOL_CALLS several times then FINAL; every call must
    receive the original (non-empty) tool set.
    """
    handlerCalls: List[Dict[str, Any]] = []
    _registerDummyTool(llmService, handlerCalls)
    generateTextMock = _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult("call_1"),
            _makeToolCallResult("call_2"),
            _makeToolCallResult("call_3"),
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData={},
        maxRounds=None,
    )

    assert generateTextMock.call_count == 4
    for i in range(4):
        assert _toolNamesAtCall(generateTextMock, i) == {
            DUMMY_TOOL_NAME
        }, f"call {i} should still offer the tool under maxRounds=None"


async def testMaxRoundsZeroDropsImmediately(llmService: LLMService, mockModel: Mock, mockChatSettings: Mock) -> None:
    """``maxRounds=0`` drops tools on the very first generateText call.

    roundN starts at 0 and the guard ``roundN >= maxRounds`` (0 >= 0) fires on
    iteration one, so the first call is made with ``tools == []``.
    """
    handlerCalls: List[Dict[str, Any]] = []
    _registerDummyTool(llmService, handlerCalls)
    generateTextMock = _wireMocks(
        llmService,
        generateSideEffects=[
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData={},
        maxRounds=0,
    )

    assert generateTextMock.call_count == 1
    assert _toolNamesAtCall(generateTextMock, 0) == set()
    # Handler never ran because tools were dropped before the first call.
    assert handlerCalls == []


async def testMaxRoundsTerminatesWhenModelKeepsReturningToolCallsPostBudget(
    llmService: LLMService, mockModel: Mock, mockChatSettings: Mock
) -> None:
    """A glitching model emitting native TOOL_CALLS forever post-budget cannot hang the loop.

    Regression for the post-budget infinite-iteration gap (Gate-1 IMPORTANT
    finding). With the budget exhausted and ``tools=[]`` offered, a loose
    provider may keep returning native ``TOOL_CALLS``. Before the fix the
    ``TOOL_CALLS`` branch always re-iterated (appending "tool not available"
    results) -> the loop never terminated, burning API calls / hanging the
    request. After the fix the post-budget ``TOOL_CALLS`` falls through to
    ``else: break`` and a fallback answer is synthesized.

    The scripted ``generateText`` uses a FINITE side-effect list so an unbounded
    loop would raise ``StopAsyncIteration`` (fail loudly) rather than hang.
    """
    handlerCalls: List[Dict[str, Any]] = []
    _registerDummyTool(llmService, handlerCalls)
    # 2 budget rounds execute (rounds 0, 1); the rest are post-budget
    # glitching TOOL_CALLS. A finite list means an unbounded loop raises once
    # exhausted instead of hanging forever.
    glitchingCalls: List[ModelRunResult] = [_makeToolCallResult(f"call_{i}") for i in range(8)]
    generateTextMock = _wireMocks(llmService, generateSideEffects=glitchingCalls)

    result = await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData={},
        maxRounds=2,
    )

    # (a) Returned instead of looping forever -> no StopAsyncIteration raised.
    # (b) Non-empty fallback text synthesized (the model returned none), and
    #     the result is reported as FINAL.
    assert result.resultText == POST_BUDGET_FALLBACK_TEXT
    assert result.status == ModelResultStatus.FINAL
    # (b.0) The cap-hit signal is surfaced for this post-budget termination.
    assert result.roundLimitHit is True
    # (b.1) The synthesized FINAL carries no stale unexecuted tool calls even
    #       though the glitching model kept emitting native TOOL_CALLS.
    assert result.toolCalls == []
    # (c) Exactly one post-budget generateText call: 2 budget rounds + 1
    #     steering round that returned TOOL_CALLS -> break.
    assert generateTextMock.call_count == 3
    # Handler ran only on the 2 pre-budget rounds; post-budget calls never
    # reached the execution branch.
    assert len(handlerCalls) == 2


async def testMaxRoundsNegativeRaises(llmService: LLMService, mockModel: Mock, mockChatSettings: Mock) -> None:
    """A negative ``maxRounds`` raises ValueError immediately (fail-fast).

    Without this guard a negative value would behave like 0 by accident of the
    ``>=`` comparison firing on roundN=0. No network call should be made.
    """
    generateTextMock = _wireMocks(llmService, generateSideEffects=[_makeFinalResult("done")])

    with pytest.raises(ValueError):
        await llmService.generateTextViaLLM(
            messages=[ModelMessage(role="user", content="hi")],
            chatId=None,
            chatSettings=mockChatSettings,
            modelKey=mockModel,
            fallbackModelKey=mockModel,
            useTools=False,
            extraData={},
            maxRounds=-1,
        )

    # Validation runs before any model call.
    assert generateTextMock.call_count == 0


async def testMaxRoundsSteeringUsesUserRoleWhenNoSystemMessage(
    llmService: LLMService, mockModel: Mock, mockChatSettings: Mock
) -> None:
    """With no leading system message, the steering directive falls back to ``role="user"``.

    Provider-safety (MINOR 1): the YC SDK provider may reject a mid-stream
    ``role="system"`` message. When there is no leading system message to fold
    into, the directive is appended as a universally-accepted ``role="user"``
    message rather than a mid-stream system one.
    """
    handlerCalls: List[Dict[str, Any]] = []
    _registerDummyTool(llmService, handlerCalls)
    generateTextMock = _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult("call_1"),
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        # No leading system message.
        messages=[ModelMessage(role="user", content="hi")],
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData={},
        maxRounds=1,
    )

    postBudgetMessages = _messagesAtCall(generateTextMock, 1)
    steeringMessages = [m for m in postBudgetMessages if STEERING_TEXT in (m.content or "")]
    # Exactly one message carries the directive, and it uses the user role
    # (NOT a mid-stream system message).
    assert len(steeringMessages) == 1
    assert steeringMessages[0].role == "user"
    # No mid-stream system message was introduced.
    assert all(m.role != "system" for m in postBudgetMessages)


# ============================================================================
# roundLimitHit signal + error-status propagation (Gate-2 review decisions)
# ============================================================================


async def testMaxRounds_setsRoundLimitHitOnExhaustion(
    llmService: LLMService,
    mockModel: Mock,
    mockChatSettings: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Post-budget termination sets ``result.roundLimitHit = True`` + warns.

    Gate-2 Decision 1. With ``maxRounds=2`` the first two TOOL_CALLS rounds
    execute within budget; the third round (roundN has reached 2) is
    post-budget and the model returns a FINAL with usable text. The cap WAS
    hit, so ``roundLimitHit`` must be ``True`` even though no fallback was
    synthesized (the model's own text is kept). The service-level warning is
    also emitted so the cap-hit is visible in logs for all callers.
    """
    handlerCalls: List[Dict[str, Any]] = []
    _registerDummyTool(llmService, handlerCalls)
    generateTextMock = _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult("call_1"),  # round 0: within budget
            _makeToolCallResult("call_2"),  # round 1: within budget
            _makeFinalResult("done"),  # round 2: exhausted -> break
        ],
    )

    with caplog.at_level(logging.WARNING, logger="internal.services.llm.service"):
        result = await llmService.generateTextViaLLM(
            messages=[ModelMessage(role="user", content="hi")],
            chatId=None,
            chatSettings=mockChatSettings,
            modelKey=mockModel,
            fallbackModelKey=mockModel,
            useTools=True,
            extraData={},
            maxRounds=2,
        )

    # The cap was hit on the third round.
    assert result.roundLimitHit is True
    # The model's own text is kept (no fallback synthesized — it was non-empty).
    assert result.resultText == "done"
    assert result.status == ModelResultStatus.FINAL
    assert generateTextMock.call_count == 3
    # Service-level warning is emitted with the maxRounds value and callId.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("hit maxRounds cap (2)" in r.getMessage() for r in warnings)


async def testMaxRounds_noRoundLimitHitWhenWithinBudget(
    llmService: LLMService, mockModel: Mock, mockChatSettings: Mock
) -> None:
    """Normal completion within budget leaves ``roundLimitHit = False``.

    Gate-2 Decision 1 (backward-compat). With ``maxRounds=5`` and a single
    FINAL response on round 0, the budget is never exhausted, so the flag
    stays at its default ``False``.
    """
    handlerCalls: List[Dict[str, Any]] = []
    _registerDummyTool(llmService, handlerCalls)
    generateTextMock = _wireMocks(
        llmService,
        generateSideEffects=[
            _makeFinalResult("done"),  # round 0: within budget -> break
        ],
    )

    result = await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData={},
        maxRounds=5,
    )

    assert result.roundLimitHit is False
    assert result.resultText == "done"
    assert generateTextMock.call_count == 1


@pytest.mark.parametrize(
    "errorStatus",
    [
        ModelResultStatus.ERROR,
        ModelResultStatus.CONTENT_FILTER,
        ModelResultStatus.UNKNOWN,
    ],
    ids=["ERROR", "CONTENT_FILTER", "UNKNOWN"],
)
async def testMaxRounds_propagatesErrorStatusPostBudget(
    llmService: LLMService,
    mockModel: Mock,
    mockChatSettings: Mock,
    errorStatus: ModelResultStatus,
) -> None:
    """A genuine error status post-budget propagates untouched (not masked).

    Gate-2 Decision 2. The old guard ``if budgetExhausted and not
    ret.resultText:`` masked ERROR/CONTENT_FILTER/UNKNOWN into FINAL+fallback,
    hiding genuine failures. The tightened guard synthesizes a fallback ONLY
    for empty FINAL or post-budget TOOL_CALLS, so error statuses keep their
    original status + empty text and callers can detect the failure. The cap
    is still hit, so ``roundLimitHit`` is ``True``.

    Scripted with ``maxRounds=2``: two within-budget TOOL_CALLS rounds, then a
    post-budget round returning the parametrized error status with empty text.
    """
    handlerCalls: List[Dict[str, Any]] = []
    _registerDummyTool(llmService, handlerCalls)
    generateTextMock = _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult("call_1"),  # round 0: within budget
            _makeToolCallResult("call_2"),  # round 1: within budget
            _makeStatusResult(errorStatus, ""),  # round 2: exhausted -> break
        ],
    )

    result = await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=None,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData={},
        maxRounds=2,
    )

    # The genuine error status propagates — NOT rewritten to FINAL.
    assert result.status == errorStatus
    # No fallback text synthesized — resultText stays empty so callers see the
    # failure (not a plausible-looking "best answer" that masks the error).
    assert result.resultText == ""
    # The cap was still hit on the post-budget round.
    assert result.roundLimitHit is True
    assert generateTextMock.call_count == 3
