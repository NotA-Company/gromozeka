"""Tests for AbstractModel structured-output methods.

Covers:
- generateStructured raises NotImplementedError when support_structured_output=False.
- generateStructured with support_structured_output=True propagates the inner
  NotImplementedError from the default _generateStructured implementation.
- generateStructured honours the contextSize * 2 budget guard.
- getInfo() includes support_structured_output with the configured value.
- generateStructuredWithFallBack invokes fallback on error status.
- generateStructuredWithFallBack sets isFallback=True on the fallback result.
"""

from collections.abc import Sequence
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock

import pytest

from lib.ai.abstract import AbstractLLMProvider, AbstractModel
from lib.ai.models import ModelMessage, ModelResultStatus, ModelRunResult, ModelStructuredResult

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

    async def generateImage(self, messages: Sequence[ModelMessage]) -> ModelRunResult:
        """Return a placeholder image result.

        Args:
            messages: Conversation history.

        Returns:
            Placeholder ModelRunResult.
        """
        return ModelRunResult(rawResult=None, status=ModelResultStatus.FINAL)


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
        extraConfig={"support_structured_output": True},
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


# ============================================================================
# Tests: generateStructuredWithFallBack
# ============================================================================


async def testGenerateStructuredWithFallBackUsesMainOnSuccess() -> None:
    """Verify generateStructuredWithFallBack returns primary result on success.

    Returns:
        None
    """
    model = _makeStructuredModel()
    fallback = _makeStructuredModel()

    expectedResult = ModelStructuredResult(rawResult=None, status=ModelResultStatus.FINAL, data={"ok": True})
    model.generateStructured = AsyncMock(return_value=expectedResult)  # type: ignore[method-assign]
    fallback.generateStructured = AsyncMock()  # type: ignore[method-assign]

    schema: Dict[str, Any] = {"type": "object"}
    messages = [ModelMessage(role="user", content="hi")]

    result = await model.generateStructuredWithFallBack(messages, fallback, schema)

    assert result is expectedResult
    assert result.isFallback is False
    fallback.generateStructured.assert_not_called()


async def testGenerateStructuredWithFallBackTriggersOnErrorStatus() -> None:
    """Verify generateStructuredWithFallBack falls back on ERROR status.

    Returns:
        None
    """
    model = _makeStructuredModel()
    fallback = _makeStructuredModel()

    errorResult = ModelStructuredResult(rawResult=None, status=ModelResultStatus.ERROR)
    fallbackResult = ModelStructuredResult(rawResult=None, status=ModelResultStatus.FINAL, data={"fallback": True})

    model.generateStructured = AsyncMock(return_value=errorResult)  # type: ignore[method-assign]
    fallback.generateStructured = AsyncMock(return_value=fallbackResult)  # type: ignore[method-assign]

    schema: Dict[str, Any] = {"type": "object"}
    messages = [ModelMessage(role="user", content="hi")]

    result = await model.generateStructuredWithFallBack(messages, fallback, schema)

    assert result is fallbackResult
    assert result.isFallback is True


async def testGenerateStructuredWithFallBackSetsFallbackFlag() -> None:
    """Verify generateStructuredWithFallBack sets isFallback=True on fallback result.

    Returns:
        None
    """
    model = _makeStructuredModel()
    fallback = _makeStructuredModel()

    # Primary raises an exception
    model.generateStructured = AsyncMock(side_effect=RuntimeError("api down"))  # type: ignore[method-assign]
    fallbackResult = ModelStructuredResult(rawResult=None, status=ModelResultStatus.FINAL, data={"y": 2})
    fallback.generateStructured = AsyncMock(return_value=fallbackResult)  # type: ignore[method-assign]

    schema: Dict[str, Any] = {"type": "object"}
    messages = [ModelMessage(role="user", content="hi")]

    result = await model.generateStructuredWithFallBack(messages, fallback, schema)

    assert result.isFallback is True
    assert result.data == {"y": 2}
