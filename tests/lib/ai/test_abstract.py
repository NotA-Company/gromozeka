"""Tests for AbstractModel structured-output methods.

Covers:
- generateStructured raises NotImplementedError when support_structured_output=False.
- generateStructured with support_structured_output=True propagates the inner
  NotImplementedError from the default _generateStructured implementation.
- generateStructured honours the contextSize * 2 budget guard.
- getInfo() includes support_structured_output with the configured value.
- generateStructured with fallbackModels invokes fallback on error status.
- generateStructured with fallbackModels sets isFallback=True on the fallback result.
- image-bearing message sequences are serialized before the generation-gate
  token estimation, so a valid native-vision request reaches the provider
  instead of being rejected with "Context too large" (Gate 2 regression);
  oversized real TEXT input is still rejected by the same guard.

Also covers generateEmbeddings:
- success path returns the inner vector.
- transient failures retry up to ``attempts`` times.
- all-fail surfaces a RuntimeError.
- support_embeddings=False raises NotImplementedError.
- empty text raises ValueError.
- attempts<1 raises ValueError.
- supportsEmbedding property reads support_embeddings from extraConfig.
"""

import asyncio
import io
import random
from collections.abc import Sequence
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from lib.ai.abstract import AbstractLLMProvider, AbstractModel
from lib.ai.models import ModelImagesMessage, ModelMessage, ModelResultStatus, ModelRunResult, ModelStructuredResult
from lib.stats import NullStatsStorage, StatsStorage

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
        *,
        modelId: str,
        modelVersion: str,
        contextSize: int,
        statsStorage: StatsStorage,
        extraConfig: Dict[str, Any] = {},
        customParams: Optional[Dict[str, Any]] = None,
    ) -> AbstractModel:
        """Add a model stub.

        Args:
            name: Model name.
            modelId: Model identifier.
            modelVersion: Model version.
            contextSize: Context window size.
            statsStorage: Stats storage instance.
            extraConfig: Extra configuration.
            customParams: Per-model custom parameters (temperature, etc.).

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
        customParams={"temperature": 0.5},
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
        customParams={"temperature": 0.5},
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
        customParams={"temperature": 0.5},
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


def testGetInfoSupportImageInputDefaultsFalse() -> None:
    """Verify getInfo includes support_image_input=False when not configured.

    Returns:
        None
    """
    model = _makeNoStructuredModel()
    info = model.getInfo()

    assert "support_image_input" in info
    assert info["support_image_input"] is False


def testGetInfoSupportImageInputPassthroughTrue() -> None:
    """Verify getInfo reports the configured support_image_input value.

    Returns:
        None
    """
    model = _NoStructuredModel(
        provider=_makeProvider(),
        modelId="vision-model",
        modelVersion="1.0",
        customParams={"temperature": 0.5},
        contextSize=4096,
        statsStorage=NullStatsStorage(),
        extraConfig={"support_image_input": True},
    )
    info = model.getInfo()

    assert info["support_image_input"] is True


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
        model._generateEmbeddings = AsyncMock(side_effect=[asyncio.TimeoutError("transient"), [1.0, 2.0]])
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
        model._generateEmbeddings = AsyncMock(side_effect=asyncio.TimeoutError("fail"))
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


# ============================================================================
# getEstimateTokensCount — inline base64 data URIs are estimation-invisible
# (native-vision Phase 2b; design v1 §3.4)
# ============================================================================


class TestEstimateTokensCountImageDataUris:
    """Pin the estimator's blindness to inline base64 image payloads.

    A multimodal ``image_url`` data URI carries ~0.5MB of base64 per
    normalized photo while the model bills it as ~1-3k image tokens. The
    char-based estimator must replace each data URI with a short placeholder
    (design v1 §3.4: image tokens are invisible to it) so image-bearing
    requests do not force context condensing on every call.

    Replacement engages only at the trusted input boundary: the whole input
    must be a serialized message list (every element a role+content message
    dict — the ``[message.toDict() ...]`` shape message-estimation call
    sites pass). Message-shaped structures found INSIDE a non-message input
    (e.g. a JSON Schema ``examples`` entry) never re-arm normalization.
    Bare schemas, arbitrary structured payloads, image-block shapes in
    non-message inputs, data URIs inside ordinary text content, non-image
    MIME types, quoted examples, and plain-string inputs are real sent
    characters and must keep being counted — otherwise text-only requests
    or schema data could bypass context sizing.
    """

    def testImageDataUriCountsAsPlaceholder(self) -> None:
        """A huge data URI estimates the same as its short placeholder text.

        Returns:
            None
        """
        model = _makeNoStructuredModel()
        hugeUri = "data:image/jpeg;base64," + "A" * 500_000
        withUri = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": hugeUri}}]}]
        withPlaceholder = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "<image-data>"}}]}]

        assert model.getEstimateTokensCount(withUri) == model.getEstimateTokensCount(withPlaceholder)

    def testEstimateStaysTextDrivenWithImages(self) -> None:
        """With images neutralized, the estimate matches the text-only baseline.

        Message-shaped input: a multipart user message whose content carries
        the text part plus a discriminator-less image block (provider
        payloads sometimes omit ``type``) — the real normalization contract.

        Returns:
            None
        """
        model = _makeNoStructuredModel()
        hugeUri = "data:image/png;base64," + "B" * 1_000_000
        textPart = [{"type": "text", "text": "describe the picture"}]
        textOnly = [{"role": "user", "content": textPart}]
        withImage = [{"role": "user", "content": [*textPart, {"image_url": {"url": hugeUri}}]}]

        estimate = model.getEstimateTokensCount(withImage)
        baseline = model.getEstimateTokensCount(textOnly)
        assert estimate < baseline + 100

    def testPlainDataUriStringCountedAsText(self) -> None:
        """A raw string input containing a data URI is counted as text, not neutralized.

        Plain-string inputs pass through untouched: without a surrounding
        image-block structure there is no evidence the data URI is an image
        payload, and counting it as a placeholder would let text-only
        requests bypass context sizing.

        Returns:
            None
        """
        model = _makeNoStructuredModel()
        hugeUri = "data:image/webp;base64," + "C" * 500_000

        # ~500k characters / 3.5 * 1.1 coeff ≈ 157k "tokens" — full text counted.
        assert model.getEstimateTokensCount(f'"url": "{hugeUri}"') > 100_000

    def testDataUriInTextContentCountedAsText(self) -> None:
        """A data URI inside a message's TEXT content is counted, not stripped.

        The estimator must not pattern-match arbitrary serialized values:
        this text message really sends every one of those characters to the
        model, so collapsing it to a placeholder would understate the request
        size (regression for the over-broad regex estimator).

        Returns:
            None
        """
        model = _makeNoStructuredModel()
        textMessage = [{"role": "user", "content": "data:text/plain;base64," + "A" * 500_000}]

        assert model.getEstimateTokensCount(textMessage) > 100_000

    def testNonImageDataUriInImageBlockCountedAsText(self) -> None:
        """A non-image MIME data URI inside a message's ``image_url`` block stays counted.

        Only ``data:image/...`` payloads are estimation noise; a
        ``data:text/plain`` URI carries real text the model will read.
        Message-shaped input: the MIME check runs at a genuine message
        image-content position.

        Returns:
            None
        """
        model = _makeNoStructuredModel()
        textUri = "data:text/plain;base64," + "B" * 500_000
        block = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": textUri}}]}]

        assert model.getEstimateTokensCount(block) > 100_000

    def testQuotedDataUriExampleInTextCountedAsText(self) -> None:
        """A quoted data-URI example inside a text block keeps being counted.

        A text field that merely MENTIONS a data URI (e.g. documentation or a
        schema example) must not be collapsed: the old regex matched the
        quoted URI inside the serialized JSON string.

        Returns:
            None
        """
        model = _makeNoStructuredModel()
        quotedExample = 'Use the format "data:image/jpeg;base64,' + "D" * 500_000 + '" when embedding images.'
        textMessage = [{"role": "user", "content": quotedExample}]

        assert model.getEstimateTokensCount(textMessage) > 100_000

    def testSchemaExampleImageBlockCountedVerbatim(self) -> None:
        """A JSON-schema example shaped like an image block is counted, not neutralized.

        ``generateStructured`` estimates the schema itself in addition to the
        messages (``tokensCount = ... + self.getEstimateTokensCount(schema)``).
        A schema example mimicking an image block is schema DATA the request
        actually carries, not an image attachment — collapsing it would
        substantially under-count the context-size guard (reviewer
        counterexample: a 500k-char example must keep being counted).

        Returns:
            None
        """
        model = _makeNoStructuredModel()
        schema = {"type": "object", "examples": [{"image_url": {"url": "data:image/jpeg;base64," + "A" * 500_000}}]}

        assert model.getEstimateTokensCount(schema) > 100_000

    def testMessageShapedSchemaExampleCountedVerbatim(self) -> None:
        """A message-shaped schema EXAMPLE instance is counted, not normalized.

        Regression for the recursive-discovery undercount: a JSON Schema can
        carry a message-shaped EXAMPLE INSTANCE under ``examples`` whose
        ``role`` value is a plain string, satisfying any message-shape
        predicate found mid-recursion. Normalization is decided once at the
        trusted input boundary — the schema is a dict, not a message list,
        so nothing discovered inside it may re-arm image replacement and the
        full 500k-char payload stays counted (reviewer counterexample).

        Returns:
            None
        """
        model = _makeNoStructuredModel()
        schema = {
            "type": "object",
            "properties": {"role": {"type": "string"}, "content": {"type": "array"}},
            "examples": [
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + "A" * 500_000}}],
                }
            ],
        }

        assert model.getEstimateTokensCount(schema) > 100_000

    def testImageBlockOutsideMessageContentCountedAsText(self) -> None:
        """An image-block shape OUTSIDE a message's content position stays counted.

        Normalization is scoped to message image-content positions: the same
        dict shape appearing as bare structured data (here: a sibling of the
        message objects in the request list, i.e. an ordinary JSON payload)
        is not recognized as an image attachment and is counted verbatim.

        Returns:
            None
        """
        model = _makeNoStructuredModel()
        hugeUri = "data:image/jpeg;base64," + "F" * 500_000
        bareBlock = [{"role": "user", "content": "describe the picture"}, {"image_url": {"url": hugeUri}}]

        assert model.getEstimateTokensCount(bareBlock) > 100_000

    def testEstimationDoesNotMutateInput(self) -> None:
        """The estimation representation is non-mutating: input data unchanged.

        Returns:
            None
        """
        model = _makeNoStructuredModel()
        hugeUri = "data:image/jpeg;base64," + "E" * 10_000
        block = {"type": "image_url", "image_url": {"url": hugeUri}}
        data = [{"role": "user", "content": [block]}]

        model.getEstimateTokensCount(data)

        assert data[0]["content"][0]["image_url"]["url"] == hugeUri


# ============================================================================
# generateText / generateStructured — image-bearing message OBJECT lists must
# be serialized before the generation-gate estimation (native-vision Gate 2
# regression: base64 counted as text at the final context guard)
# ============================================================================


def _makeLargePngBytes(size: int = 128) -> bytes:
    """Build a genuinely valid, incompressibly large PNG in memory.

    The image is real (libmagic detects ``image/png``, Pillow encodes it) and
    its noise content keeps it ~``size * size * 3`` bytes, so the base64
    payload ``toDict()`` embeds is decisively larger than a small context
    budget.

    Args:
        size: Square image side length in pixels (default 128).

    Returns:
        bytes: Valid PNG bytes.
    """
    noise = random.Random(42).randbytes(size * size * 3)
    buf = io.BytesIO()
    Image.frombytes("RGB", (size, size), noise).save(buf, format="PNG")
    return buf.getvalue()


class TestGenerationGateWithImageMessages:
    """A valid native-vision request must reach the provider, not the context guard.

    Regression (Gate 2, native-vision): ``generateText``/``generateStructured``
    passed raw ``ModelMessage`` OBJECTS to ``getEstimateTokensCount``. The
    estimator's trusted boundary (:func:`lib.ai.abstract._isMessageList`)
    recognizes only serialized dicts, so an object list fell through to
    ``json.dumps(..., default=str)`` and ``ModelImagesMessage.__str__`` ->
    ``toDict()`` embedded the FULL base64 payload of every attached image —
    the estimate inflated past ``contextSize * 2`` and the request was
    rejected with "Context too large" WITHOUT calling the provider, even
    though the identical request serialized as dicts (the condensation
    path's ``[v.toDict() ...]`` shape) estimates correctly.

    The guard itself must keep rejecting genuinely oversized TEXT requests —
    only the image-payload miscount is fixed.
    """

    async def testGenerateTextReachesProviderWithLargeNativeVisionImage(self) -> None:
        """ModelImagesMessage objects pass the gate and reach _generateText.

        Returns:
            None
        """
        model = _makeStructuredModel(contextSize=100)
        model._generateText = AsyncMock(
            return_value=ModelRunResult(rawResult=None, status=ModelResultStatus.FINAL, resultText="vision ok")
        )
        messages = [
            ModelImagesMessage(role="user", content="describe the picture", images=[bytearray(_makeLargePngBytes())])
        ]

        result = await model.generateText(messages)

        assert result.status is ModelResultStatus.FINAL
        assert result.resultText == "vision ok"
        model._generateText.assert_awaited_once()

    async def testGenerateTextFallbackAttemptReachesProviderWithImage(self) -> None:
        """The fallback wrapper's per-model gate also lets image requests through.

        Returns:
            None
        """
        primary = _makeStructuredModel(contextSize=100)
        fallback = _makeStructuredModel(contextSize=100)
        primary._generateText = AsyncMock(
            return_value=ModelRunResult(rawResult=None, status=ModelResultStatus.FINAL, resultText="primary ok")
        )
        messages = [
            ModelImagesMessage(role="user", content="describe the picture", images=[bytearray(_makeLargePngBytes())])
        ]

        result = await primary.generateText(messages, fallbackModels=[fallback])

        assert result.status is ModelResultStatus.FINAL
        assert result.resultText == "primary ok"
        assert result.isFallback is False
        primary._generateText.assert_awaited_once()

    async def testGenerateStructuredReachesProviderWithImage(self) -> None:
        """generateStructured's equivalent estimate also serializes image messages.

        Returns:
            None
        """
        model = _makeStructuredModel(contextSize=100)
        model._generateStructured = AsyncMock(  # type: ignore[method-assign]
            return_value=ModelStructuredResult(rawResult=None, status=ModelResultStatus.FINAL, data={"ok": True})
        )
        messages = [
            ModelImagesMessage(role="user", content="describe the picture", images=[bytearray(_makeLargePngBytes())])
        ]
        schema: Dict[str, Any] = {"type": "object"}

        result = await model.generateStructured(messages, schema)

        assert result.status is ModelResultStatus.FINAL
        assert result.data == {"ok": True}
        model._generateStructured.assert_awaited_once()

    async def testGenerateTextStillRejectsOversizedText(self) -> None:
        """Genuinely oversized TEXT input is still rejected without calling the provider.

        Returns:
            None
        """
        model = _makeStructuredModel(contextSize=100)
        model._generateText = AsyncMock(
            return_value=ModelRunResult(rawResult=None, status=ModelResultStatus.FINAL, resultText="should not run")
        )
        messages = [ModelMessage(role="user", content="word " * 500)]  # ~2500 chars ≈ 785 tokens

        result = await model.generateText(messages)

        assert result.status is ModelResultStatus.ERROR
        assert result.error is not None
        assert "Context too large" in str(result.error)
        model._generateText.assert_not_awaited()
