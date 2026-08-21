"""Tests for LLM tool call statistics recording.

Tests the integration of StatsStorage with LLMService tool execution,
including recording of successful calls, errors, elapsed time, and proper
handling of edge cases (raising tools, missing ensuredMessage, stats disabled).
"""

import datetime
from typing import Any, Dict, Optional, Sequence, Union
from unittest.mock import AsyncMock, Mock

import pytest

# Import necessary models
from internal.bot.models import ChatType, EnsuredMessage, MessageRecipient, MessageSender
from internal.services.llm.models import ExtraDataDict
from internal.services.llm.service import LLMService
from lib.ai.abstract import AbstractModel
from lib.ai.manager import LLMManager
from lib.ai.models import LLMToolCall, ModelMessage, ModelResultStatus, ModelRunResult
from lib.stats.stats_storage import StatsStorage
from tests.utils import createAsyncMock

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
def mockStatsStorage() -> AsyncMock:
    """Create a mock StatsStorage for testing.

    Returns:
        An AsyncMock(spec=StatsStorage) with record() mock.
    """
    storage = AsyncMock(spec=StatsStorage)
    storage.record = AsyncMock()
    return storage


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


@pytest.fixture
def ensuredMessage() -> EnsuredMessage:
    """Create a test EnsuredMessage with sender.id and recipient.id set.

    Returns:
        An EnsuredMessage with minimal required attributes for stats recording.
    """
    return EnsuredMessage(
        sender=MessageSender(id=12345, name="Test User", username="testuser"),
        recipient=MessageRecipient(id=67890, chatType=ChatType.PRIVATE),
        messageId=123,
        date=datetime.datetime.now(datetime.timezone.utc),
        messageText="Test message",
    )


@pytest.fixture
def extraData(ensuredMessage: EnsuredMessage) -> ExtraDataDict:
    """Create extraData dict with ensuredMessage.

    Args:
        ensuredMessage: The EnsuredMessage fixture.

    Returns:
        An ExtraDataDict with ``{"ensuredMessage": ensuredMessage}``.
    """
    return {"ensuredMessage": ensuredMessage}


# ============================================================================
# Helpers
# ============================================================================


def _wireMocks(
    service: LLMService,
    *,
    generateSideEffects: Sequence[ModelRunResult],
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
    generateTextMock.side_effect = generateSideEffects
    service.generateText = generateTextMock
    return generateTextMock


DUMMY_TOOL_NAME: str = "dummy_tool"
"""Name of the single tool registered by these tests' harness."""


def _registerDummyTool(service: LLMService, callLog: Optional[list] = None, returnsError: bool = False) -> str:
    """Register a dummy tool whose handler records each invocation into callLog.

    Args:
        service: The LLMService instance to register the tool on.
        callLog: A list the handler appends a dict to on every call, so tests
            can assert on execution count / timing.
        returnsError: If True, handler returns an error dict instead of success.

    Returns:
        The tool name that was registered.
    """

    async def dummyHandler(extraData: Optional[Dict[str, object]] = None, **kwargs: Any) -> Union[str, Dict[str, Any]]:
        """Record-then-return handler for the dummy tool.

        Args:
            extraData: Extra data dict passed by the service (unused).
            **kwargs: Tool parameters (unused).

        Returns:
            The string ``"ok"`` or an error dict.
        """
        if callLog is not None:
            callLog.append(dict(kwargs))
        if returnsError:
            return {"error": "Tool execution failed"}
        return "ok"

    service.registerTool(DUMMY_TOOL_NAME, "dummy tool for stats tests", [], dummyHandler)
    return DUMMY_TOOL_NAME


def _makeToolCallResult(
    toolName: str = DUMMY_TOOL_NAME, callId: str = "call_1", errorMessage: Optional[str] = None
) -> ModelRunResult:
    """Build a native TOOL_CALLS result invoking a tool.

    Args:
        toolName: The tool name to invoke.
        callId: The tool-call id to assign.
        errorMessage: Optional error message for synthesized errors.

    Returns:
        A ``ModelRunResult`` with ``TOOL_CALLS`` status and a single
        tool call carrying no parameters.
    """
    return ModelRunResult(
        rawResult={},
        status=ModelResultStatus.TOOL_CALLS,
        resultText="",
        toolCalls=[LLMToolCall(id=callId, name=toolName, parameters={}, errorMessage=errorMessage)],
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


# ============================================================================
# Tests
# ============================================================================


async def testSuccessfulToolCallRecordsStats(
    llmService: LLMService,
    mockStatsStorage: AsyncMock,
    mockModel: Mock,
    mockChatSettings: Mock,
    extraData: ExtraDataDict,
) -> None:
    """Successful tool dispatch records correct statistics.

    Covers branch 2 (real dispatch): registered tool + ``useTools=True`` →
    handler awaited with timing; result "ok" → ``is_error=0``.
    """
    handlerCalls: list[dict] = []
    toolName = _registerDummyTool(llmService, handlerCalls)
    llmService.injectStatsStorage(mockStatsStorage)

    _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult(toolName, "call_1"),
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=67890,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData=extraData,
    )

    # Tool handler was called
    assert len(handlerCalls) == 1

    # Stats were recorded once for the tool call
    mockStatsStorage.record.assert_called_once()
    callArgs = mockStatsStorage.record.call_args

    # Check stats dict
    stats = callArgs.kwargs["stats"]
    assert stats["tool_call_count"] == 1
    assert stats["tool_exec_count"] == 1
    assert stats["elapsed_time"] > 0.0
    assert stats["is_error"] == 0

    # Check labels
    labels = callArgs.kwargs["labels"]
    assert labels["user_id"] == "12345"
    assert labels["toolName"] == toolName

    # Check consumerId
    assert callArgs.kwargs["consumerId"] == "67890"


async def testErrorDictRecordsAsError(
    llmService: LLMService,
    mockStatsStorage: AsyncMock,
    mockModel: Mock,
    mockChatSettings: Mock,
    extraData: ExtraDataDict,
) -> None:
    """Tool returning error dict records ``is_error=1``.

    Covers branch 2 with error return: handler returns ``{"error": "x"}`` →
    ``is_error=1``.
    """
    handlerCalls: list[dict] = []
    toolName = _registerDummyTool(llmService, handlerCalls, returnsError=True)
    llmService.injectStatsStorage(mockStatsStorage)

    _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult(toolName, "call_1"),
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=67890,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData=extraData,
    )

    mockStatsStorage.record.assert_called_once()
    callArgs = mockStatsStorage.record.call_args
    stats = callArgs.kwargs["stats"]
    assert stats["is_error"] == 1
    assert stats["tool_call_count"] == 1
    assert stats["tool_exec_count"] == 1
    assert stats["elapsed_time"] > 0.0


async def testSynthesizedErrorRecordsAsError(
    llmService: LLMService,
    mockStatsStorage: AsyncMock,
    mockModel: Mock,
    mockChatSettings: Mock,
    extraData: ExtraDataDict,
) -> None:
    """Synthesized error from broken tool call records ``is_error=1`` and ``elapsed_time=0.0``.

    Covers branch 1 (synthesized error): ``LLMToolCall(..., errorMessage="boom")`` →
    no handler call, ``is_error=1``, ``elapsed_time=0.0``.
    """
    toolName = DUMMY_TOOL_NAME
    llmService.injectStatsStorage(mockStatsStorage)

    _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult(toolName, "call_1"),
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=67890,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData=extraData,
    )

    mockStatsStorage.record.assert_called_once()
    callArgs = mockStatsStorage.record.call_args
    stats = callArgs.kwargs["stats"]
    assert stats["is_error"] == 1
    assert stats["tool_call_count"] == 1
    assert "tool_exec_count" not in stats
    assert stats["elapsed_time"] == 0.0
    assert callArgs.kwargs["labels"]["toolName"] == toolName


async def testUnavailableToolRecordsAsError(
    llmService: LLMService,
    mockStatsStorage: AsyncMock,
    mockModel: Mock,
    mockChatSettings: Mock,
    extraData: ExtraDataDict,
) -> None:
    """Unavailable tool records ``is_error=1`` and ``elapsed_time=0.0``.

    Covers branch 3 (unavailable tool): ``LLMToolCall(name="not_registered")`` →
    ``is_error=1``, ``elapsed_time=0.0``.
    """
    toolName = "unavailable_tool"
    llmService.injectStatsStorage(mockStatsStorage)

    _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult(toolName, "call_1"),
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=67890,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData=extraData,
    )

    mockStatsStorage.record.assert_called_once()
    callArgs = mockStatsStorage.record.call_args
    stats = callArgs.kwargs["stats"]
    assert stats["is_error"] == 1
    assert stats["tool_call_count"] == 1
    assert "tool_exec_count" not in stats
    assert stats["elapsed_time"] == 0.0
    assert callArgs.kwargs["labels"]["toolName"] == toolName


async def testRaisingToolPropagatesUnrecorded(
    llmService: LLMService,
    mockStatsStorage: AsyncMock,
    mockModel: Mock,
    mockChatSettings: Mock,
    extraData: ExtraDataDict,
) -> None:
    """Tool that raises propagates exception and records nothing.

    Covers branch 4 (raising tool): handler raises → exception propagates,
    NOTHING recorded (D4 contract).
    """
    toolName = DUMMY_TOOL_NAME

    async def raisingHandler(extraData: Optional[Dict[str, object]] = None, **kwargs: Any) -> str:
        """Handler that always raises."""
        raise ValueError("Tool raised an exception")

    llmService.registerTool(toolName, "raising tool", [], raisingHandler)
    llmService.injectStatsStorage(mockStatsStorage)

    _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult(toolName, "call_1"),
        ],
    )

    # Exception should propagate
    with pytest.raises(ValueError, match="Tool raised an exception"):
        await llmService.generateTextViaLLM(
            messages=[ModelMessage(role="user", content="hi")],
            chatId=67890,
            chatSettings=mockChatSettings,
            modelKey=mockModel,
            fallbackModelKey=mockModel,
            useTools=True,
            extraData=extraData,
        )

    # No stats recorded (exception before record() call)
    mockStatsStorage.record.assert_not_called()


async def testMissingEnsuredMessageSkipsRecording(
    llmService: LLMService,
    mockStatsStorage: AsyncMock,
    mockModel: Mock,
    mockChatSettings: Mock,
) -> None:
    """Missing ensuredMessage in extraData skips recording gracefully.

    Covers branch 5: missing ensuredMessage → skip recording entirely.
    """
    handlerCalls: list[dict] = []
    toolName = _registerDummyTool(llmService, handlerCalls)
    llmService.injectStatsStorage(mockStatsStorage)

    _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult(toolName, "call_1"),
            _makeFinalResult("done"),
        ],
    )

    extraDataNoMessage: ExtraDataDict = {}  # No ensuredMessage

    await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=67890,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData=extraDataNoMessage,
    )

    # Tool handler was still called
    assert len(handlerCalls) == 1

    # No stats recorded when ensuredMessage is missing
    mockStatsStorage.record.assert_not_called()


async def testNullStatsStorageWorks(
    llmService: LLMService,
    mockModel: Mock,
    mockChatSettings: Mock,
    extraData: ExtraDataDict,
) -> None:
    """NullStatsStorage (stats disabled) default works without errors.

    Covers default behavior when no ``injectStatsStorage`` is called.
    """
    handlerCalls: list[dict] = []
    toolName = _registerDummyTool(llmService, handlerCalls)

    # No injectStatsStorage -> defaults to NullStatsStorage

    _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult(toolName, "call_1"),
            _makeFinalResult("done"),
        ],
    )

    # Should complete without errors
    result = await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=67890,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData=extraData,
    )

    # Tool was called
    assert len(handlerCalls) == 1
    # Result was returned
    assert result.resultText == "done"


async def testMultipleToolCallsRecordEach(
    llmService: LLMService,
    mockStatsStorage: AsyncMock,
    mockModel: Mock,
    mockChatSettings: Mock,
    extraData: ExtraDataDict,
) -> None:
    """Multiple tool calls in one iteration record each separately.

    Verifies that each tool call results in a separate ``stats.record()`` call
    with proper consumerId and labels.
    """
    handlerCalls: list[dict] = []
    toolName = _registerDummyTool(llmService, handlerCalls)
    llmService.injectStatsStorage(mockStatsStorage)

    _wireMocks(
        llmService,
        generateSideEffects=[
            ModelRunResult(
                rawResult={},
                status=ModelResultStatus.TOOL_CALLS,
                resultText="",
                toolCalls=[
                    LLMToolCall(id="call_1", name=toolName, parameters={}),
                    LLMToolCall(id="call_2", name=toolName, parameters={}),
                    LLMToolCall(id="call_3", name=toolName, parameters={}),
                ],
            ),
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=67890,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData=extraData,
    )

    # Each tool call recorded separately
    assert mockStatsStorage.record.call_count == 3
    assert len(handlerCalls) == 3

    # All calls have the same consumerId and labels
    for call in mockStatsStorage.record.call_args_list:
        assert call.kwargs["consumerId"] == "67890"
        assert call.kwargs["labels"]["user_id"] == "12345"
        assert call.kwargs["labels"]["toolName"] == toolName
        stats = call.kwargs["stats"]
        assert stats["tool_call_count"] == 1
        assert stats["tool_exec_count"] == 1
        assert stats["is_error"] == 0
        assert stats["elapsed_time"] > 0.0


async def testElapsedTimeIsNonNegativeFloat(
    llmService: LLMService,
    mockStatsStorage: AsyncMock,
    mockModel: Mock,
    mockChatSettings: Mock,
    extraData: ExtraDataDict,
) -> None:
    """Elapsed time is a non-negative float for all branches.

    Verifies that ``elapsed_time`` is properly measured and recorded as a
    non-negative float for successful tool calls.
    """
    handlerCalls: list[dict] = []
    toolName = _registerDummyTool(llmService, handlerCalls)
    llmService.injectStatsStorage(mockStatsStorage)

    _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult(toolName, "call_1"),
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=67890,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData=extraData,
    )

    callArgs = mockStatsStorage.record.call_args
    elapsed = callArgs.kwargs["stats"]["elapsed_time"]
    stats = callArgs.kwargs["stats"]
    assert stats["tool_exec_count"] == 1
    assert isinstance(elapsed, float)
    assert elapsed >= 0.0


async def testDoneTrueErrorNoneRecordsAsNonError(
    llmService: LLMService,
    mockStatsStorage: AsyncMock,
    mockModel: Mock,
    mockChatSettings: Mock,
    extraData: ExtraDataDict,
) -> None:
    """Tool returning {"done": True, "error": None} records is_error=0.

    Tests the new isError heuristic: a success dict with "error": None
    should NOT be miscounted as an error.

    Args:
        llmService: LLM service fixture
        mockStatsStorage: Mock stats storage
        mockModel: Mock model fixture
        mockChatSettings: Mock chat settings
        extraData: Extra data dict with ensuredMessage
    """

    async def successWithNoneErrorHandler(
        extraData: Optional[Dict[str, object]] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        """Handler that returns {"done": True, "error": None}."""
        return {"done": True, "error": None}

    toolName = "success_with_none_error"
    llmService.registerTool(toolName, "tool returning done=True with error=None", [], successWithNoneErrorHandler)
    llmService.injectStatsStorage(mockStatsStorage)

    _wireMocks(
        llmService,
        generateSideEffects=[
            _makeToolCallResult(toolName, "call_1"),
            _makeFinalResult("done"),
        ],
    )

    await llmService.generateTextViaLLM(
        messages=[ModelMessage(role="user", content="hi")],
        chatId=67890,
        chatSettings=mockChatSettings,
        modelKey=mockModel,
        fallbackModelKey=mockModel,
        useTools=True,
        extraData=extraData,
    )

    mockStatsStorage.record.assert_called_once()
    callArgs = mockStatsStorage.record.call_args
    stats = callArgs.kwargs["stats"]
    assert stats["is_error"] == 0
    assert stats["tool_call_count"] == 1
    assert stats["tool_exec_count"] == 1
    assert stats["elapsed_time"] > 0.0
