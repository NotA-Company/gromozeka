"""Tests for AbstractModel structured-output methods.

Covers:
- generateStructured raises NotImplementedError when support_structured_output=False.
- generateStructured with support_structured_output=True propagates the inner
  NotImplementedError from the default _generateStructured implementation.
- generateStructured honours the contextSize * 2 budget guard.
- getInfo() includes support_structured_output with the configured value.
- generateStructured with fallbackModels invokes fallback on error status.
- generateStructured with fallbackModels sets isFallback=True on the fallback result.

Also covers generateEmbeddings:
- success path returns the inner vector.
- transient failures retry up to ``attempts`` times.
- all-fail surfaces a RuntimeError.
- support_embeddings=False raises NotImplementedError.
- empty text raises ValueError.
- attempts<1 raises ValueError.
- supportsEmbedding property reads support_embeddings from extraConfig.
"""

from collections.abc import Sequence
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, patch

import pytest

from lib.ai.abstract import AbstractLLMProvider, AbstractModel
from lib.ai.models import ModelMessage, ModelResultStatus, ModelRunResult, ModelStructuredResult
from lib.stats import NullStatsStorage

# ============================================================================
# Minimal concrete subclasses for testing
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


class _NoStructuredModel(AbstractModel):
    """Model stub with support_structured_output=False (the default).

    Used to verify that generateStructured raises NotImplementedError
    before ever reaching _generateStructured.

    Attributes:
        provider: Parent provider instance.
        modelId: Model identifier.
    """

    async def _generateText(self, messages: Sequence[ModelMessage], tools: Optional[Any] = None) -> ModelRunResult:
        """Return a placeholder result.

        Args:
            messages: Conversation history.
            tools: Optional tools (unused).

        Returns:
            Placeholder ModelRunResult.
        """
        return ModelRunResult(rawResult=None, status=ModelResultStatus.FINAL)

    async def _generateImage(self, messages: Sequence[ModelMessage]) -> ModelRunResult:
        """Return a placeholder image result.

        Args:
            messages: Conversation history.

        Returns:
            Placeholder ModelRunResult.
        """
        return ModelRunResult(rawResult=None, status=ModelResultStatus.FINAL)

    async def _generateEmbeddings(self, text: str) -> list[float]:
        """Return a placeholder embedding vector.

        Args:
            text: Input text (unused by the stub).

        Returns:
            Placeholder zero-vector of fixed length.
        """
        return [0.0] * 4


class _StructuredSupportedModel(_NoStructuredModel):
    """Model stub with support_structured_output=True.

    Inherits the default _generateStructured (raises NotImplementedError)
    to verify that the public generateStructured propagates it.

    Attributes:
        provider: Parent provider instance.
        modelId: Model identifier.
    """


def _makeProvider() -> _StubProvider:
    """Create a _StubProvider instance for use in model constructors.

    Returns:
        _StubProvider with empty config.
    """
    return _StubProvider(config={})


def _makeNoStructuredModel(contextSize: int = 4096) -> _NoStructuredModel:
    """Create a model with support_structured_output=False.

    Args:
        contextSize: Model context window size.

    Returns:
        _NoStructuredModel instance.
    """
    return _NoStructuredModel(
        provider=_makeProvider(),
        modelId="no-struct",
        modelVersion="1.0",
        temperature=0.5,
        contextSize=contextSize,
        statsStorage=NullStatsStorage(),
        extraConfig={"support_structured_output": False},
    )


def _makeStructuredModel(contextSize: int = 4096) -> _StructuredSupportedModel:
    """Create a model with support_structured_output=True.

    Args:
        contextSize: Model context window size.

    Returns:
        _StructuredSupportedModel instance.
    """
    return _StructuredSupportedModel(
        provider=_makeProvider(),
        modelId="struct-model",
        modelVersion="1.0",
        temperature=0.5,
        contextSize=contextSize,
        statsStorage=NullStatsStorage(),
        extraConfig={"support_structured_output": True},
    )


def _makeEmbeddingModel(supportEmbeddings: bool = True) -> _NoStructuredModel:
    """Create a model with the ``support_embeddings`` capability flag set.

    Args:
        supportEmbeddings: Value of the ``support_embeddings`` flag in
            ``extraConfig`` (default True). When False, the public
            ``generateEmbeddings`` rejects with NotImplementedError.

    Returns:
        _NoStructuredModel instance (the stub's ``_generateEmbeddings``
        returns a fixed-length zero vector, which the tests override
        with an ``AsyncMock`` when they need a custom return value).
    """
    return _NoStructuredModel(
        provider=_makeProvider(),
        modelId="emb-model",
        modelVersion="1.0",
        temperature=0.5,
        contextSize=4096,
        statsStorage=NullStatsStorage(),
        extraConfig={"support_embeddings": supportEmbeddings},
    )


# ============================================================================
# Tests: generateStructured capability gate
# ============================================================================


async def testGenerateStructuredRaisesWhenNotSupported() -> None:
    """Verify generateStructured raises NotImplementedError when flag is False.

    Returns:
        None
    """
    model = _makeNoStructuredModel()
    schema: Dict[str, Any] = {"type": "object", "properties": {"x": {"type": "integer"}}}
    messages = [ModelMessage(role="user", content="hi")]

    with pytest.raises(NotImplementedError, match="isn't supported"):
        await model.generateStructured(messages, schema)


async def testGenerateStructuredPropagatesInnerNotImplementedError() -> None:
    """Verify generateStructured propagates NotImplementedError from _generateStructured.

    A model with support_structured_output=True but using the default
    _generateStructured (which raises NotImplementedError) should let that
    error propagate out of the public generateStructured.

    Returns:
        None
    """
    model = _makeStructuredModel()
    schema: Dict[str, Any] = {"type": "object", "properties": {"x": {"type": "integer"}}}
    messages = [ModelMessage(role="user", content="hi")]

    with pytest.raises(NotImplementedError, match="isn't implemented"):
        await model.generateStructured(messages, schema)


# ============================================================================
# Tests: context budget guard
# ============================================================================


async def testGenerateStructuredContextBudgetGuard() -> None:
    """Verify generateStructured returns ERROR when tokens exceed contextSize * 2.

    With a small contextSize and large messages the budget guard fires and
    returns a ModelStructuredResult(status=ERROR) without calling
    _generateStructured.

    Returns:
        None
    """
    model = _makeStructuredModel(contextSize=10)
    # Large enough message to blow past the budget
    bigText = "word " * 500  # ~500 tokens estimated
    messages = [ModelMessage(role="user", content=bigText)]
    schema: Dict[str, Any] = {"type": "object"}

    result = await model.generateStructured(messages, schema)

    assert isinstance(result, ModelStructuredResult)
    assert result.status is ModelResultStatus.ERROR
    assert result.data is None
    assert result.error is not None
    assert "Context too large" in str(result.error)


# ============================================================================
# Tests: getInfo includes support_structured_output
# ============================================================================


def testGetInfoIncludesSupportStructuredOutputFalse() -> None:
    """Verify getInfo includes support_structured_output=False when not configured.

    Returns:
        None
    """
    model = _makeNoStructuredModel()
    info = model.getInfo()

    assert "support_structured_output" in info
    assert info["support_structured_output"] is False


def testGetInfoIncludesSupportStructuredOutputTrue() -> None:
    """Verify getInfo includes support_structured_output=True when configured.

    Returns:
        None
    """
    model = _makeStructuredModel()
    info = model.getInfo()

    assert "support_structured_output" in info
    assert info["support_structured_output"] is True


# Tests: _runWithFallback helper


async def testRunWithFallbackEmptyListRaisesValueError() -> None:
    """Verify _runWithFallback raises ValueError when models list is empty.

    Returns:
        None
    """
    model = _makeStructuredModel()

    with pytest.raises(ValueError, match="models list cannot be empty"):
        await model._runWithFallback(
            models=[],
            call=lambda m: m.generateText(messages=[], tools=None),  # type: ignore[arg-type]
            retType=ModelRunResult,
        )


async def testRunWithFallbackDuplicateModelInvokedTwice() -> None:
    """Verify _runWithFallback invokes the same model twice when it appears twice in the list.

    Returns:
        None
    """
    model = _makeStructuredModel()
    errorResult = ModelRunResult(rawResult=None, status=ModelResultStatus.ERROR)
    model.generateText = AsyncMock(return_value=errorResult)  # type: ignore[method-assign]

    messages = [ModelMessage(role="user", content="hi")]

    await model._runWithFallback(
        models=[model, model],
        call=lambda m: m.generateText(messages=messages, tools=None),
        retType=ModelRunResult,
    )

    assert model.generateText.call_count == 2


# ============================================================================
# Tests: generateText with fallbackModels parameter
# ============================================================================


async def testGenerateTextWithFallbackModelsUsesPrimaryOnSuccess() -> None:
    """Verify generateText with fallbackModels uses primary on success.

    Returns:
        None
    """
    primary = _makeStructuredModel()
    fallback = _makeStructuredModel()

    messages = [ModelMessage(role="user", content="hi")]

    result = await primary.generateText(messages, fallbackModels=[fallback])

    assert result.status is ModelResultStatus.FINAL
    assert result.isFallback is False


async def testGenerateTextWithFallbackModelsFallsBackOnException() -> None:
    """Verify generateText with fallbackModels falls back when primary raises exception.

    Returns:
        None
    """
    primary = _makeStructuredModel()
    fallback = _makeStructuredModel()

    primary._generateText = AsyncMock(side_effect=RuntimeError("network error"))
    fallbackResult = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="fallback success",
    )
    fallback._generateText = AsyncMock(return_value=fallbackResult)

    messages = [ModelMessage(role="user", content="hi")]

    result = await primary.generateText(messages, fallbackModels=[fallback])

    assert result.status is ModelResultStatus.FINAL
    assert result.isFallback is True
    assert result.resultText == "fallback success"


async def testGenerateTextWithFallbackModelsFallsBackOnErrorStatus() -> None:
    """Verify generateText with fallbackModels falls back when primary returns ERROR status.

    Returns:
        None
    """
    primary = _makeStructuredModel()
    fallback = _makeStructuredModel()

    errorResult = ModelRunResult(rawResult=None, status=ModelResultStatus.ERROR)
    fallbackResult = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="fallback success",
    )

    primary._generateText = AsyncMock(return_value=errorResult)
    fallback._generateText = AsyncMock(return_value=fallbackResult)

    messages = [ModelMessage(role="user", content="hi")]

    result = await primary.generateText(messages, fallbackModels=[fallback])

    assert result.status is ModelResultStatus.FINAL
    assert result.isFallback is True
    assert result.resultText == "fallback success"


async def testGenerateTextWithFallbackModelsChainExhaustedReturnsLastResult() -> None:
    """Verify generateText with fallbackModels returns last result when all models fail.

    Returns:
        None
    """
    primary = _makeStructuredModel()
    fallback = _makeStructuredModel()

    primaryError = ModelRunResult(rawResult=None, status=ModelResultStatus.ERROR)
    fallbackError = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.UNSPECIFIED,
        resultText="fallback failed",
    )

    primary._generateText = AsyncMock(return_value=primaryError)
    fallback._generateText = AsyncMock(return_value=fallbackError)

    messages = [ModelMessage(role="user", content="hi")]

    result = await primary.generateText(messages, fallbackModels=[fallback])

    assert result.status is ModelResultStatus.UNSPECIFIED
    assert result.isFallback is True
    assert result.resultText == "fallback failed"


async def testGenerateTextWithFallbackModelsMultipleFallbacks() -> None:
    """Verify generateText with fallbackModels works with multiple fallback models.

    Returns:
        None
    """
    primary = _makeStructuredModel()
    fallback1 = _makeStructuredModel()
    fallback2 = _makeStructuredModel()

    primaryError = ModelRunResult(rawResult=None, status=ModelResultStatus.ERROR)
    fallback1Error = ModelRunResult(rawResult=None, status=ModelResultStatus.ERROR)
    fallback2Result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="third time's charm",
    )

    primary._generateText = AsyncMock(return_value=primaryError)
    fallback1._generateText = AsyncMock(return_value=fallback1Error)
    fallback2._generateText = AsyncMock(return_value=fallback2Result)

    messages = [ModelMessage(role="user", content="hi")]

    result = await primary.generateText(messages, fallbackModels=[fallback1, fallback2])

    assert result.status is ModelResultStatus.FINAL
    assert result.isFallback is True
    assert result.resultText == "third time's charm"


# ============================================================================
# Tests: generateImage with fallbackModels parameter
# ============================================================================


async def testGenerateImageWithFallbackModelsUsesPrimaryOnSuccess() -> None:
    """Verify generateImage with fallbackModels uses primary on success.

    Returns:
        None
    """
    primary = _makeStructuredModel()
    fallback = _makeStructuredModel()

    messages = [ModelMessage(role="user", content="draw a cat")]

    result = await primary.generateImage(messages, fallbackModels=[fallback])

    assert result.status is ModelResultStatus.FINAL
    assert result.isFallback is False


async def testGenerateImageWithFallbackModelsFallsBackOnErrorStatus() -> None:
    """Verify generateImage with fallbackModels falls back when primary returns ERROR status.

    Returns:
        None
    """
    primary = _makeStructuredModel()
    fallback = _makeStructuredModel()

    errorResult = ModelRunResult(rawResult=None, status=ModelResultStatus.ERROR)
    fallbackResult = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="https://example.com/fallback.png",
    )

    primary._generateImage = AsyncMock(return_value=errorResult)
    fallback._generateImage = AsyncMock(return_value=fallbackResult)

    messages = [ModelMessage(role="user", content="draw a cat")]

    result = await primary.generateImage(messages, fallbackModels=[fallback])

    assert result.status is ModelResultStatus.FINAL
    assert result.isFallback is True
    assert result.resultText == "https://example.com/fallback.png"


# ============================================================================
# Tests: generateStructured with fallbackModels parameter
# ============================================================================


async def testGenerateStructuredWithFallbackModelsUsesPrimaryOnSuccess() -> None:
    """Verify generateStructured with fallbackModels uses primary on success.

    Returns:
        None
    """
    primary = _makeStructuredModel()
    fallback = _makeStructuredModel()

    primaryResult = ModelStructuredResult(rawResult=None, status=ModelResultStatus.FINAL, data={"primary": True})
    primary.generateStructured = AsyncMock(return_value=primaryResult)  # type: ignore[method-assign]
    fallback.generateStructured = AsyncMock()  # type: ignore[method-assign]

    schema = {"type": "object"}
    messages = [ModelMessage(role="user", content="hi")]

    result = await primary.generateStructured(messages, schema, fallbackModels=[fallback])

    assert result is primaryResult
    assert result.isFallback is False
    fallback.generateStructured.assert_not_called()


async def testGenerateStructuredWithFallbackModelsFallsBackOnErrorStatus() -> None:
    """Verify generateStructured with fallbackModels falls back on ERROR status.

    Returns:
        None
    """
    primary = _makeStructuredModel()
    fallback = _makeStructuredModel()

    errorResult = ModelStructuredResult(rawResult=None, status=ModelResultStatus.ERROR)
    fallbackResult = ModelStructuredResult(rawResult=None, status=ModelResultStatus.FINAL, data={"fallback": True})

    primary._generateStructured = AsyncMock(return_value=errorResult)  # type: ignore[method-assign]
    fallback._generateStructured = AsyncMock(return_value=fallbackResult)  # type: ignore[method-assign]

    schema = {"type": "object"}
    messages = [ModelMessage(role="user", content="hi")]

    result = await primary.generateStructured(messages, schema, fallbackModels=[fallback])

    assert result.status is ModelResultStatus.FINAL
    assert result.isFallback is True
    assert result.data == {"fallback": True}


async def testGenerateStructuredWithFallbackModelsReturnsLastOnTotalFailure() -> None:
    """Verify generateStructured with fallbackModels returns last result when all models fail.

    Returns:
        None
    """
    primary = _makeStructuredModel()
    fallback = _makeStructuredModel()

    primaryError = ModelStructuredResult(rawResult=None, status=ModelResultStatus.ERROR)
    fallbackError = ModelStructuredResult(rawResult=None, status=ModelResultStatus.ERROR)

    primary._generateStructured = AsyncMock(return_value=primaryError)  # type: ignore[method-assign]
    fallback._generateStructured = AsyncMock(return_value=fallbackError)  # type: ignore[method-assign]

    schema = {"type": "object"}
    messages = [ModelMessage(role="user", content="hi")]

    result = await primary.generateStructured(messages, schema, fallbackModels=[fallback])

    assert result.status is ModelResultStatus.ERROR
    assert result.isFallback is True


# ============================================================================
# Tests: generateEmbeddings
# ============================================================================


class TestGenerateEmbeddings:
    """Tests for generateEmbeddings method on AbstractModel."""

    async def test_generateEmbeddings_success(self) -> None:
        """Successful call returns embedding vector.

        Returns:
            None
        """
        model = _makeEmbeddingModel()
        model._generateEmbeddings = AsyncMock(return_value=[1.0, 2.0])
        result = await model.generateEmbeddings("hello")
        assert result == [1.0, 2.0]

    async def test_generateEmbeddings_retries(self) -> None:
        """Retries on transient failure, succeeds on second attempt.

        Returns:
            None
        """
        model = _makeEmbeddingModel()
        model._generateEmbeddings = AsyncMock(side_effect=[ValueError("transient"), [1.0, 2.0]])
        with patch("lib.ai.abstract.asyncio.sleep", new_callable=AsyncMock) as mockSleep:
            result = await model.generateEmbeddings("hello", attempts=2)
        assert result == [1.0, 2.0]
        assert model._generateEmbeddings.await_count == 2
        mockSleep.assert_awaited_once()

    async def test_generateEmbeddings_all_fail(self) -> None:
        """All attempts fail → raises RuntimeError.

        Returns:
            None
        """
        model = _makeEmbeddingModel()
        model._generateEmbeddings = AsyncMock(side_effect=ValueError("fail"))
        with patch("lib.ai.abstract.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="after 3 attempts"):
                await model.generateEmbeddings("hello")

    async def test_generateEmbeddings_not_supported(self) -> None:
        """supportsEmbedding=False → raises NotImplementedError.

        Returns:
            None
        """
        model = _makeEmbeddingModel(supportEmbeddings=False)
        with pytest.raises(NotImplementedError):
            await model.generateEmbeddings("hello")

    async def test_generateEmbeddings_empty_text(self) -> None:
        """Empty text raises ValueError.

        Returns:
            None
        """
        model = _makeEmbeddingModel()
        with pytest.raises(ValueError):
            await model.generateEmbeddings("")

    async def test_generateEmbeddings_bad_attempts(self) -> None:
        """attempts <= 0 raises ValueError.

        Returns:
            None
        """
        model = _makeEmbeddingModel()
        with pytest.raises(ValueError):
            await model.generateEmbeddings("hello", attempts=0)

    def test_supportsEmbedding_flag(self) -> None:
        """supportsEmbedding property reads from config.

        Returns:
            None
        """
        modelTrue = _makeEmbeddingModel(supportEmbeddings=True)
        assert modelTrue.supportsEmbedding is True
        modelFalse = _makeEmbeddingModel(supportEmbeddings=False)
        assert modelFalse.supportsEmbedding is False
