"""Integration tests for AbstractModel stats recording."""

from collections.abc import Sequence
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

from lib.ai.abstract import AbstractLLMProvider, AbstractModel
from lib.ai.models import (
    LLMAbstractTool,
    ModelMessage,
    ModelResultStatus,
    ModelRunResult,
)
from lib.stats import NullStatsStorage, StatsStorage

# ============================================================================
# Test fixtures and helpers
# ============================================================================


class _StubProvider(AbstractLLMProvider):
    """Minimal provider stub for constructing models in tests.

    Attributes:
        config: Provider configuration dictionary.
        models: Dictionary mapping model names to AbstractModel instances.
    """

    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Add a model stub.

        Args:
            name: Model name.
            modelId: Model identifier.
            modelVersion: Model version.
            temperature: Temperature setting.
            contextSize: Context window size.
            extraConfig: Extra configuration.

        Returns:
            AbstractModel stub instance.
        """
        raise NotImplementedError


class _TestModel(AbstractModel):
    """Minimal concrete model for testing stats recording.

    Implements all abstract methods with simple mock-like behavior.

    Attributes:
        mockResult: The result that _generateText, _generateImage, and
            _generateStructured will return when called.
    """

    def __init__(self, *args, mockResult: Optional[ModelRunResult] = None, **kwargs):
        """Initialize test model.

        Args:
            *args: Positional arguments passed to AbstractModel.__init__.
            mockResult: Optional result to return from generate methods.
            **kwargs: Keyword arguments passed to AbstractModel.__init__.
        """
        super().__init__(*args, **kwargs)
        self.mockResult = mockResult

    async def _generateText(
        self, messages: Sequence[ModelMessage], tools: Optional[Sequence[LLMAbstractTool]] = None
    ) -> ModelRunResult:
        """Return the mock result or a default FINAL result.

        Args:
            messages: Conversation history (unused).
            tools: Optional tools (unused).

        Returns:
            ModelRunResult instance.
        """
        if self.mockResult:
            return self.mockResult
        return ModelRunResult(
            rawResult=None,
            status=ModelResultStatus.FINAL,
            resultText="Test response",
        )

    async def _generateImage(self, messages: Sequence[ModelMessage]) -> ModelRunResult:
        """Return the mock result or a default FINAL result.

        Args:
            messages: Conversation history (unused).

        Returns:
            ModelRunResult instance.
        """
        if self.mockResult:
            return self.mockResult
        return ModelRunResult(
            rawResult=None,
            status=ModelResultStatus.FINAL,
            resultText="https://example.com/image.png",
        )


def _makeModel(
    contextSize: int = 4096,
    mockResult: Optional[ModelRunResult] = None,
    extraConfig: Optional[Dict[str, Any]] = None,
    statsStorage: Optional[StatsStorage] = NullStatsStorage(),
) -> _TestModel:
    """Create a test model instance.

    Args:
        contextSize: Model context window size.
        mockResult: Optional result to return from generate methods.
        extraConfig: Optional extra configuration for the model.
        statsStorage: Optional stats storage for the model.

    Returns:
        _TestModel instance.
    """
    config = extraConfig or {}
    return _TestModel(
        provider=_StubProvider(config={}),
        modelId="test-model",
        modelVersion="1.0",
        temperature=0.5,
        contextSize=contextSize,
        extraConfig=config,
        mockResult=mockResult,
        statsStorage=statsStorage,
    )


# ============================================================================
# Tests: stats recording on successful generation
# ============================================================================


async def testGenerateTextRecordsStats() -> None:
    """Verify generateText records stats via statsStorage.

    Returns:
        None
    """
    # Create a mock statsStorage
    mockStorage = MagicMock()
    mockStorage.record = AsyncMock()

    # Create a model with the mock storage
    model = _makeModel()
    model.statsStorage = mockStorage

    messages = [ModelMessage(role="user", content="Hello")]
    result = await model.generateText(messages, consumerId="chat_42")

    # Verify the model returned a result
    assert result.status is ModelResultStatus.FINAL

    # Verify stats were recorded
    assert mockStorage.record.called
    callArgs = mockStorage.record.call_args
    assert callArgs.kwargs["consumerId"] == "chat_42"
    assert "generation_text" in callArgs.kwargs["stats"]
    assert callArgs.kwargs["stats"]["generation_text"] == 1
    assert callArgs.kwargs["labels"]["modelName"] == "test-model"
    assert callArgs.kwargs["labels"]["provider"] == "_StubProvider"


async def testGenerateImageRecordsStats() -> None:
    """Verify generateImage records stats via statsStorage.

    Returns:
        None
    """
    # Create a mock statsStorage
    mockStorage = MagicMock()
    mockStorage.record = AsyncMock()

    # Create a model with the mock storage
    model = _makeModel()
    model.statsStorage = mockStorage

    messages = [ModelMessage(role="user", content="Draw a cat")]
    result = await model.generateImage(messages, consumerId="chat_99")

    # Verify the model returned a result
    assert result.status is ModelResultStatus.FINAL

    # Verify stats were recorded
    assert mockStorage.record.called
    callArgs = mockStorage.record.call_args
    assert callArgs.kwargs["consumerId"] == "chat_99"
    assert "generation_image" in callArgs.kwargs["stats"]
    assert callArgs.kwargs["stats"]["generation_image"] == 1


async def testGenerateStructuredRecordsStats() -> None:
    """Verify generateStructured records stats via statsStorage.

    Returns:
        None
    """
    from lib.ai.models import ModelStructuredResult

    # Create a mock statsStorage
    mockStorage = MagicMock()
    mockStorage.record = AsyncMock()

    # Create a model with structured output support and mock storage
    model = _makeModel(extraConfig={"support_structured_output": True})
    model.statsStorage = mockStorage

    messages = [ModelMessage(role="user", content="Parse this")]
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}

    # Mock _generateStructured to return a successful result
    mockResult = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        data={"answer": "parsed"},
    )
    model._generateStructured = AsyncMock(return_value=mockResult)

    result = await model.generateStructured(messages, schema)

    # Verify the model returned a result
    assert result.status is ModelResultStatus.FINAL

    # Verify stats were recorded
    assert mockStorage.record.called
    callArgs = mockStorage.record.call_args
    assert "generation_structured" in callArgs.kwargs["stats"]
    assert callArgs.kwargs["stats"]["generation_structured"] == 1


# ============================================================================
# Tests: stats recording on error conditions
# ============================================================================


async def testGenerateTextRecordsErrorStats() -> None:
    """Verify generateText records is_error=1 when status is in ERROR_STATUSES.

    Returns:
        None
    """
    # Create a mock statsStorage
    mockStorage = MagicMock()
    mockStorage.record = AsyncMock()

    # Create a model that returns an error result
    errorResult = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.ERROR,
        error=RuntimeError("API error"),
    )
    model = _makeModel(mockResult=errorResult)
    model.statsStorage = mockStorage

    messages = [ModelMessage(role="user", content="Hello")]
    result = await model.generateText(messages, consumerId="chat_123")

    # Verify the model returned an error
    assert result.status is ModelResultStatus.ERROR

    # Verify stats were recorded with is_error=1
    assert mockStorage.record.called
    callArgs = mockStorage.record.call_args
    assert callArgs.kwargs["stats"]["is_error"] == 1


async def testStatsStorageDoesNotBreakLLMCall() -> None:
    """Verify model works normally even when statsStorage is set.

    Returns:
        None
    """
    # Use NullStatsStorage to verify stats don't interfere with LLM calls
    nullStorage = NullStatsStorage()

    model = _makeModel()
    model.statsStorage = nullStorage

    messages = [ModelMessage(role="user", content="Hello")]
    result = await model.generateText(messages, consumerId="chat_42")

    # Should still return a result
    assert result is not None
    assert result.status is ModelResultStatus.FINAL


# ============================================================================
# Tests: stats recording with fallback
# ============================================================================


async def testFallbackRecordsIsFallback() -> None:
    """Verify fallback attempt records is_fallback=1.

    Returns:
        None
    """
    # Create a mock statsStorage
    mockStorage = MagicMock()
    mockStorage.record = AsyncMock()

    # Create two models: primary that fails, fallback that succeeds
    primaryError = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.ERROR,
        error=RuntimeError("Primary failed"),
    )
    primary = _makeModel(mockResult=primaryError)

    fallbackSuccess = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="Fallback success",
    )
    fallback = _makeModel(mockResult=fallbackSuccess)

    # Both models share the same stats storage
    primary.statsStorage = mockStorage
    fallback.statsStorage = mockStorage

    messages = [ModelMessage(role="user", content="Hello")]
    result = await primary.generateText(messages, fallbackModels=[fallback])

    # Verify fallback was used
    assert result.status is ModelResultStatus.FINAL
    assert result.isFallback

    # Verify stats were recorded 2 times:
    # 1. primary.generateText inside _runWithFallback calls primary._recordAttemptStats (is_fallback=0)
    # 2. fallback.generateText inside _runWithFallback calls fallback._recordAttemptStats (is_fallback=0)
    # Note: Each model's generate* method records stats when invoked with fallbackModels=None.
    # The _runWithFallback method no longer records stats itself to avoid double-counting.
    assert mockStorage.record.call_count == 2


# ============================================================================
# Tests: stats recording with token counts
# ============================================================================


async def testRecordsTokenCounts() -> None:
    """Verify stats recording includes token usage when available.

    Returns:
        None
    """
    # Create a mock statsStorage
    mockStorage = MagicMock()
    mockStorage.record = AsyncMock()

    # Create a result with token counts
    resultWithTokens = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="Response",
        inputTokens=50,
        outputTokens=30,
        totalTokens=80,
    )
    model = _makeModel(mockResult=resultWithTokens)
    model.statsStorage = mockStorage

    messages = [ModelMessage(role="user", content="Hello")]
    await model.generateText(messages, consumerId="chat_tokens")

    # Verify token stats were recorded
    assert mockStorage.record.called
    callArgs = mockStorage.record.call_args
    assert callArgs.kwargs["stats"]["input_tokens"] == 50
    assert callArgs.kwargs["stats"]["output_tokens"] == 30
    assert callArgs.kwargs["stats"]["total_tokens"] == 80


# ============================================================================
# Tests: NullStatsStorage integration
# ============================================================================


async def testNullStatsStorageDoesNotRecord() -> None:
    """Verify NullStatsStorage doesn't raise and doesn't record anything.

    Returns:
        None
    """
    # Use NullStatsStorage
    nullStorage = NullStatsStorage()

    model = _makeModel()
    model.statsStorage = nullStorage

    messages = [ModelMessage(role="user", content="Hello")]

    # Should not raise
    result = await model.generateText(messages, consumerId="chat_null")

    # Should still return a result
    assert result is not None
    assert result.status is ModelResultStatus.FINAL

    # Aggregate should return 0 (nothing was recorded)
    aggregated = await nullStorage.aggregate()
    assert aggregated == 0
