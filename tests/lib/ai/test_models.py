"""Tests for ModelStructuredResult and ModelRunResult.__str__ touch-up.

Covers:
- ModelStructuredResult instantiation with all fields and with defaults.
- ModelStructuredResult.data defaults to None.
- __slots__ enforcement: setting result.data works; setting result.bogus raises
  AttributeError.
- str(result) includes the data field when set on a ModelStructuredResult.
- str() on a plain ModelRunResult does NOT include a data entry.
- Auto-iteration via __slots__ MRO walk.
- Per-field renderer overrides (_STR_RENDERERS).
- Default-skip rules (None, False, empty containers).
- Integer 0 tokens are NOT skipped.
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
# __str__ — data field inclusion  (Phase 1 tests, updated for new format)
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

    The new __str__ auto-iterates __slots__ and skips None values by default,
    so data=None must not appear in the output.

    Returns:
        None
    """
    result = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.ERROR,
        data=None,
    )
    text = str(result)
    # data=None is filtered by the default-skip rule (None -> omit)
    assert "data=" not in text


def testModelRunResultStrDoesNotIncludeDataKey() -> None:
    """Verify that a plain ModelRunResult.__str__ does not include a data key.

    The plain class has no 'data' slot, so MRO iteration never produces it.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="hello",
    )
    text = str(result)
    assert "data=" not in text


# ============================================================================
# __str__ — new auto-iteration / renderer tests
# ============================================================================


def testStrIteratesSlots() -> None:
    """__str__ includes expected fields and omits result/error/mediaData by default.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        resultText="hello",
    )
    result.setFallback(True)
    text = str(result)

    assert "status=FINAL" in text
    assert "resultText='hello'" in text
    assert "isFallback=True" in text
    # result slot has a renderer that always returns _OMIT
    assert "result=" not in text
    # error and mediaData are None → renderer returns _OMIT / default skips
    assert "error=" not in text
    assert "mediaData=" not in text
    # toolCalls is an empty list → default-skip (empty container)
    assert "toolCalls=" not in text


def testStrSkipsFalsyByDefault() -> None:
    """isFallback=False and isToolsUsed=False are omitted from output.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
    )
    # Both default to False
    text = str(result)
    assert "isFallback" not in text
    assert "isToolsUsed" not in text


def testStrShowsZeroTokens() -> None:
    """Integer 0 token counts are NOT filtered even though 0 is falsy.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        inputTokens=0,
        outputTokens=0,
        totalTokens=0,
    )
    text = str(result)
    assert "inputTokens=0" in text
    assert "outputTokens=0" in text
    assert "totalTokens=0" in text


def testStrRendersErrorCompactly() -> None:
    """error field is rendered as 'TypeName: message', not a full repr.

    The renderer returns a plain string, so it is emitted without extra
    quotes: ``error=ValueError: oops``.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.ERROR,
        error=ValueError("oops"),
    )
    text = str(result)
    assert "error=ValueError: oops" in text


def testStrRendersStatusByName() -> None:
    """status is rendered as the enum's symbolic name, not its repr.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.TRUNCATED_FINAL,
    )
    text = str(result)
    assert "status=TRUNCATED_FINAL" in text
    # Must NOT appear as the default enum repr
    assert "<ModelResultStatus.TRUNCATED_FINAL" not in text


def testStrOmitsRawResult() -> None:
    """The raw 'result' slot is always omitted from __str__ output.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult={"big": "object"},
        status=ModelResultStatus.FINAL,
    )
    text = str(result)
    assert "result=" not in text


def testStrRendersMediaDataLength() -> None:
    """mediaData is rendered as '<bytes len=N>' and mediaMimeType prints normally.

    The mediaData renderer returns a plain string, so it is emitted without
    extra quotes: ``mediaData=<bytes len=100>``.  mediaMimeType has no
    renderer so it falls through to the default ``repr()`` path, which
    wraps the string in single quotes.

    Returns:
        None
    """
    result = ModelRunResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        mediaData=b"x" * 100,
        mediaMimeType="image/png",
    )
    text = str(result)
    assert "mediaData=<bytes len=100>" in text
    assert "mediaMimeType='image/png'" in text


def testStrSubclassDataField() -> None:
    """ModelStructuredResult.__str__ starts with class name and includes data.

    Returns:
        None
    """
    result = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.FINAL,
        data={"x": 1},
        resultText='{"x": 1}',
    )
    text = str(result)
    assert text.startswith("ModelStructuredResult(")
    assert "data={'x': 1}" in text
    assert "status=FINAL" in text
    assert "resultText='{\"x\": 1}'" in text


def testStrSubclassDataNoneOmitted() -> None:
    """data=None on ModelStructuredResult is omitted; error IS shown.

    Returns:
        None
    """
    result = ModelStructuredResult(
        rawResult=None,
        status=ModelResultStatus.ERROR,
        data=None,
        error=Exception("oops"),
    )
    text = str(result)
    assert "data=" not in text
    assert "error=" in text
