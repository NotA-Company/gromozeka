"""Tests for ModelStructuredResult and ModelRunResult.__str__ touch-up.

Covers:
- ModelStructuredResult instantiation with all fields and with defaults.
- ModelStructuredResult.data defaults to None.
- __slots__ enforcement: setting result.data works; setting result.bogus raises
  AttributeError.
- str(result) includes the data field when set on a ModelStructuredResult.
- str() on a plain ModelRunResult does NOT include a data entry.
"""

import pytest

from lib.ai.models import ModelResultStatus, ModelRunResult, ModelStructuredResult

# ============================================================================
# ModelStructuredResult — instantiation
# ============================================================================


def testModelStructuredResultAllFields() -> None:
    """Verify that ModelStructuredResult stores all explicitly passed fields.

    Returns:
        None
    """
    rawResult = {"id": "abc"}
    data = {"answer": 42}
    err = ValueError("boom")

    result = ModelStructuredResult(
        rawResult=rawResult,
        status=ModelResultStatus.FINAL,
        data=data,
        resultText='{"answer": 42}',
        error=err,
        inputTokens=10,
        outputTokens=5,
        totalTokens=15,
    )

    assert result.status is ModelResultStatus.FINAL
    assert result.data == data
    assert result.resultText == '{"answer": 42}'
    assert result.error is err
    assert result.inputTokens == 10
    assert result.outputTokens == 5
    assert result.totalTokens == 15
    assert result.result is rawResult
    assert result.isFallback is False


def testModelStructuredResultDefaults() -> None:
    """Verify that ModelStructuredResult defaults: data=None, resultText='', etc.

    Returns:
        None
    """
    result = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.ERROR,
    )

    assert result.data is None
    assert result.resultText == ""
    assert result.error is None
    assert result.inputTokens is None
    assert result.outputTokens is None
    assert result.totalTokens is None


def testModelStructuredResultDataDefaultsToNone() -> None:
    """Verify that data attribute defaults to None without explicit kwarg.

    Returns:
        None
    """
    result = ModelStructuredResult(rawResult=None, status=ModelResultStatus.UNSPECIFIED)
    assert result.data is None


# ============================================================================
# __slots__ enforcement
# ============================================================================


def testModelStructuredResultSlotsDataAssignment() -> None:
    """Verify that assigning to result.data slot succeeds.

    Returns:
        None
    """
    result = ModelStructuredResult(rawResult=None, status=ModelResultStatus.FINAL)
    result.data = {"x": 1}
    assert result.data == {"x": 1}


def testModelStructuredResultSlotsRaisesOnUnknownAttr() -> None:
    """Verify that setting an undeclared attribute raises AttributeError.

    Returns:
        None
    """
    result = ModelStructuredResult(rawResult=None, status=ModelResultStatus.FINAL)
    with pytest.raises(AttributeError):
        result.bogus = 1  # type: ignore[attr-defined]


# ============================================================================
# __str__ — data field inclusion
# ============================================================================


def testModelStructuredResultStrIncludesData() -> None:
    """Verify that str(result) includes the data field when data is set.

    Returns:
        None
    """
    result = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        data={"nCards": 3},
        resultText='{"nCards": 3}',
    )
    text = str(result)
    assert "data" in text
    assert "nCards" in text


def testModelStructuredResultStrDataNoneOmitted() -> None:
    """Verify that str(result) omits the data key when data is None.

    Returns:
        None
    """
    result = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.ERROR,
        data=None,
    )
    text = str(result)
    # data=None should be filtered out by the {k: v ... if v is not None} dict comp
    assert '"data"' not in text


def testModelRunResultStrDoesNotIncludeDataKey() -> None:
    """Verify that a plain ModelRunResult.__str__ does not include a data key.

    The getattr guard in __str__ should return None for instances that lack
    the data slot, so the key is filtered out.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="hello",
    )
    text = str(result)
    assert '"data"' not in text
