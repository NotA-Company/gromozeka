"""Unit tests for lib.stt.formatter (pure transcript formatter).

Covers (per ``docs/plans/lib-stt-v1.md`` §6):
- Basic one/multi-segment formatting (header + ``[HH:MM:SS] text`` lines).
- Timestamp formatting, zero-padding, and hours >= 2 digits.
- Ordering: the formatter does NOT re-sort (segments emitted in given order).
- XML escaping with the ``&``-first ordering.
- Skipping whitespace-only segments.
- The ``[No speech detected]`` sentinel (no header prepended).
- Under-cap results returned unchanged.
- Deterministic head/tail truncation to an EXACT character boundary, including
  the marker digit-width fixed-point (crossing powers of 10).
- The header is counted inside the cap (output never exceeds it).
"""

import re
from typing import Tuple

import pytest

from lib.stt.formatter import UNTRUSTED_TRANSCRIPT_HEADER, formatTranscript
from lib.stt.models import (
    STTResultStatus,
    TranscriptionResult,
    TranscriptionSegment,
)

# Matches the single truncation marker and captures the omitted count.
_MARKER_RE = re.compile(r"\[\.\.\. transcript truncated; (\d+) characters omitted \.\.\.\]")


def _segment(text: str, startMs: int = 0) -> TranscriptionSegment:
    """Build a minimal TranscriptionSegment for tests.

    Args:
        text: The segment text.
        startMs: The segment start time in milliseconds.

    Returns:
        TranscriptionSegment: A segment with an empty words tuple.
    """
    return TranscriptionSegment(text=text, startMs=startMs, endMs=startMs + 1, words=())


def _result(
    segments: Tuple[TranscriptionSegment, ...],
    status: STTResultStatus = STTResultStatus.FINAL,
) -> TranscriptionResult:
    """Build a TranscriptionResult wrapping the given segments.

    Args:
        segments: The segment tuple.
        status: The result status (ignored by the formatter, kept realistic).

    Returns:
        TranscriptionResult: The assembled result.
    """
    return TranscriptionResult(status=status, segments=segments)


def _headerLen() -> int:
    """Return the length of the header including its trailing newline.

    Returns:
        int: ``len(UNTRUSTED_TRANSCRIPT_HEADER) + 1``.
    """
    return len(UNTRUSTED_TRANSCRIPT_HEADER) + 1


# ============================================================================
# Basic formatting
# ============================================================================


def testSingleSegmentFormatting() -> None:
    """A single non-empty segment yields the header plus one timestamped line.

    Returns:
        None
    """
    result = _result((_segment("First recognized segment.", startMs=3000),))
    out = formatTranscript(result, maxTranscriptChars=10000)
    expected = UNTRUSTED_TRANSCRIPT_HEADER + "\n[00:00:03] First recognized segment."
    assert out == expected


def testMultipleSegmentsFormatting() -> None:
    """Multiple segments become header + newline-joined timestamped lines.

    Returns:
        None
    """
    result = _result(
        (
            _segment("First recognized segment.", startMs=3000),
            _segment("Second recognized segment.", startMs=8000),
        )
    )
    out = formatTranscript(result, maxTranscriptChars=10000)
    expected = (
        UNTRUSTED_TRANSCRIPT_HEADER
        + "\n[00:00:03] First recognized segment."
        + "\n[00:00:08] Second recognized segment."
    )
    assert out == expected


# ============================================================================
# Timestamp formatting — zero-padding, hours >= 2 digits
# ============================================================================


@pytest.mark.parametrize(
    "startMs, expectedStamp",
    [
        (0, "00:00:00"),
        (3000, "00:00:03"),
        (65_000, "00:01:05"),  # 1 min 5 s
        (3_661_000, "01:01:01"),  # 1 h 1 min 1 s
        (3_600_000, "01:00:00"),  # exactly 1 hour
        (36_000_000, "10:00:00"),  # 10 hours, two digits preserved
        (360_000_000, "100:00:00"),  # 100 hours — width grows past 2 digits
    ],
)
def testTimestampFormatting(startMs: int, expectedStamp: str) -> None:
    """Segment start is formatted as [HH:MM:SS] with hours at least 2 digits.

    Args:
        startMs: The segment start time in milliseconds.
        expectedStamp: The expected ``HH:MM:SS`` substring.

    Returns:
        None
    """
    result = _result((_segment("text", startMs=startMs),))
    out = formatTranscript(result, maxTranscriptChars=10000)
    assert out == UNTRUSTED_TRANSCRIPT_HEADER + f"\n[{expectedStamp}] text"


# ============================================================================
# Ordering — the formatter does NOT re-sort
# ============================================================================


def testFormatterDoesNotResort() -> None:
    """Segments are emitted in the GIVEN order even when out of time order.

    Returns:
        None
    """
    result = _result(
        (
            _segment("late-first", startMs=8000),
            _segment("early-second", startMs=1000),
            _segment("mid-third", startMs=4000),
        )
    )
    out = formatTranscript(result, maxTranscriptChars=10000)
    assert out == (
        UNTRUSTED_TRANSCRIPT_HEADER + "\n[00:00:08] late-first" + "\n[00:00:01] early-second" + "\n[00:00:04] mid-third"
    )


# ============================================================================
# XML escaping — & escaped before < and >
# ============================================================================


def testXmlEscapingAmpersandFirst() -> None:
    """&, <, > are escaped, with & first so replacements are not double-escaped.

    Returns:
        None
    """
    result = _result((_segment("a<b>&c", startMs=0),))
    out = formatTranscript(result, maxTranscriptChars=10000)
    assert out == UNTRUSTED_TRANSCRIPT_HEADER + "\n[00:00:00] a&lt;b&gt;&amp;c"


def testXmlEscapingAllThreeCharacters() -> None:
    """Each special character maps to its entity independently.

    Returns:
        None
    """
    result = _result((_segment("x & y < z > w", startMs=0),))
    out = formatTranscript(result, maxTranscriptChars=10000)
    assert out == UNTRUSTED_TRANSCRIPT_HEADER + "\n[00:00:00] x &amp; y &lt; z &gt; w"


# ============================================================================
# Skip empty segments
# ============================================================================


def testWhitespaceOnlySegmentIsSkipped() -> None:
    """A segment whose stripped text is empty is omitted entirely.

    Returns:
        None
    """
    result = _result((_segment("   \t  \n", startMs=0),))
    out = formatTranscript(result, maxTranscriptChars=10000)
    assert out == "[No speech detected]"


def testMixedEmptyAndNonEmptyKeepsOnlyNonEmpty() -> None:
    """Empty segments are dropped; non-empty ones survive in their positions.

    Returns:
        None
    """
    result = _result(
        (
            _segment("keep one", startMs=1000),
            _segment("   ", startMs=2000),
            _segment("\n\t", startMs=3000),
            _segment("keep two", startMs=4000),
        )
    )
    out = formatTranscript(result, maxTranscriptChars=10000)
    assert out == (UNTRUSTED_TRANSCRIPT_HEADER + "\n[00:00:01] keep one" + "\n[00:00:04] keep two")


# ============================================================================
# No-speech sentinel — no header prepended
# ============================================================================


def testAllEmptySegmentsYieldSentinelWithoutHeader() -> None:
    """A result with only empty segments returns exactly the no-speech sentinel.

    Returns:
        None
    """
    result = _result((_segment("", startMs=0), _segment("  ", startMs=1000)))
    out = formatTranscript(result, maxTranscriptChars=10000)
    assert out == "[No speech detected]"
    assert UNTRUSTED_TRANSCRIPT_HEADER not in out


def testEmptySegmentTupleYieldSentinelWithoutHeader() -> None:
    """A result with an empty segment tuple returns the no-speech sentinel.

    Returns:
        None
    """
    result = _result(())
    out = formatTranscript(result, maxTranscriptChars=10000)
    assert out == "[No speech detected]"


# ============================================================================
# Under cap — unchanged, no marker
# ============================================================================


def testUnderCapIsUnchanged() -> None:
    """A transcript shorter than the cap is returned with no truncation marker.

    Returns:
        None
    """
    result = _result((_segment("short text", startMs=0),))
    full = UNTRUSTED_TRANSCRIPT_HEADER + "\n[00:00:00] short text"
    out = formatTranscript(result, maxTranscriptChars=len(full) + 50)
    assert out == full
    assert "truncated" not in out


def testExactlyAtCapIsUnchanged() -> None:
    """A transcript whose length equals the cap is returned unchanged.

    Returns:
        None
    """
    result = _result((_segment("edge text", startMs=0),))
    full = UNTRUSTED_TRANSCRIPT_HEADER + "\n[00:00:00] edge text"
    out = formatTranscript(result, maxTranscriptChars=len(full))
    assert out == full
    assert "truncated" not in out


# ============================================================================
# Deterministic truncation — exact boundary
# ============================================================================


def testTruncationProducesExactCapLength() -> None:
    """A long transcript truncates to EXACTLY maxTranscriptChars characters.

    Returns:
        None
    """
    body = "x" * 2000
    result = _result((_segment(body, startMs=0),))
    cap = _headerLen() + 200  # well under header + body
    out = formatTranscript(result, maxTranscriptChars=cap)
    assert len(out) == cap


def testTruncationContainsExactlyOneMarkerWithCorrectCount() -> None:
    """The truncated output has exactly one marker whose omitted count is correct.

    Returns:
        None
    """
    # The formatter's body is the timestamp prefix plus the escaped text.
    formatterBody = "[00:00:00] " + "x" * 1500
    result = _result((_segment("x" * 1500, startMs=0),))
    cap = _headerLen() + 137
    out = formatTranscript(result, maxTranscriptChars=cap)
    assert len(out) == cap

    matches = _MARKER_RE.findall(out)
    assert len(matches) == 1
    omitted = int(matches[0])
    # Independently derive head/tail/marker from the output structure.
    rest = out[_headerLen() :]
    markerMatch = _MARKER_RE.search(rest)
    assert markerMatch is not None
    head = rest[: markerMatch.start()]
    tail = rest[markerMatch.end() :]
    assert len(head) + len(tail) + len(markerMatch.group(0)) == len(rest)
    # head is a prefix of the body, tail is a suffix of the body.
    assert formatterBody.startswith(head)
    assert formatterBody.endswith(tail)
    # The omitted count matches the characters not retained from the body.
    assert omitted == len(formatterBody) - (len(head) + len(tail))


def testTruncationOddExtraCharacterGoesToHead() -> None:
    """An odd retained budget assigns the extra character to the head, not tail.

    Returns:
        None
    """
    body = "Hhead" + ("m" * 400) + "Ttail"  # distinguishable head vs tail content
    result = _result((_segment(body, startMs=0),))
    cap = _headerLen() + 101  # odd retained budget after reserving header + marker
    out = formatTranscript(result, maxTranscriptChars=cap)
    assert len(out) == cap
    rest = out[_headerLen() :]
    markerMatch = _MARKER_RE.search(rest)
    assert markerMatch is not None
    head = rest[: markerMatch.start()]
    tail = rest[markerMatch.end() :]
    # headLen = ceil(budget/2), tailLen = floor(budget/2) → headLen == tailLen + 1.
    assert len(head) == len(tail) + 1


# ============================================================================
# Deterministic truncation — marker digit-width fixed-point
# ============================================================================


def testFixedPointResolvesToExactLengthAcrossManyCaps() -> None:
    """For every cap in a wide range, truncation yields EXACTLY cap characters.

    Sweeping the cap drives the omitted count across powers of 10 (10, 100,
    1000), so the marker digit width changes mid-computation; the fixed point
    must resolve each time to an exact-length output.

    Returns:
        None
    """
    body = "q" * 5000
    result = _result((_segment(body, startMs=0),))
    bodyLinePrefix = len("[00:00:00] ")
    formatterBodyLen = bodyLinePrefix + len(body)
    fullLen = _headerLen() + formatterBodyLen
    seenDigitWidths: set[int] = set()
    # Sweep caps that stay in the head/marker/tail regime (budget >= 0). The
    # lower bound leaves headroom for the largest possible 4-digit marker so the
    # retained budget is comfortably positive; omitted then spans ~4960 down to
    # ~54, crossing the 1000 and 100 (and 10 near the top) digit boundaries.
    minCap = _headerLen() + 80
    caps = list(range(minCap, minCap + 360, 1))
    caps += list(range(minCap + 360, fullLen, 37))
    assert caps, "sweep range must be non-empty"
    for cap in caps:
        out = formatTranscript(result, maxTranscriptChars=cap)
        assert len(out) == cap, f"cap={cap}: len(out)={len(out)}"
        assert out.startswith(UNTRUSTED_TRANSCRIPT_HEADER)
        assert out.count("[... transcript truncated;") == 1
        omitted = int(_MARKER_RE.search(out).group(1))  # type: ignore[union-attr]
        seenDigitWidths.add(len(str(omitted)))
    # Confirm the sweep actually exercised multiple marker digit widths.
    assert seenDigitWidths >= {2, 3, 4}, f"expected to cross digit widths, got {seenDigitWidths}"


def testFixedPointStableAcrossDigitBoundary() -> None:
    """The fixed point converges when omitted's digit width changes mid-solve.

    Constructs a body/cap where a single naive pass would mis-size the marker,
    then asserts the resolved output is internally consistent (the marker's own
    omitted count equals exactly the body characters not retained) and exactly
    cap characters long.

    Returns:
        None
    """
    body = "r" * 5000
    bodyLinePrefix = len("[00:00:00] ")
    formatterBodyLen = bodyLinePrefix + len(body)
    result = _result((_segment(body, startMs=0),))
    # Pick a cap that lands omitted near 100 (the 2->3 digit boundary).
    cap = _headerLen() + formatterBodyLen - 100
    out = formatTranscript(result, maxTranscriptChars=cap)
    assert len(out) == cap

    markerMatch = _MARKER_RE.search(out)
    assert markerMatch is not None
    omitted = int(markerMatch.group(1))
    rest = out[_headerLen() :]
    head = rest[: markerMatch.start()]
    tail = rest[markerMatch.end() :]
    # The marker is the only one and the count equals exactly the body
    # characters not retained (head + tail are the retained prefix/suffix).
    assert rest.count("[... transcript truncated;") == 1
    assert omitted == formatterBodyLen - (len(head) + len(tail))


def testDegenerateCapNeverExceedsCap() -> None:
    """A cap too small for header + marker still yields exactly cap characters.

    Exercises the defensive hard-truncation fallback so the "output never
    exceeds cap" guarantee holds for any positive cap, including those smaller
    than the header itself.

    Returns:
        None
    """
    body = "z" * 2000
    result = _result((_segment(body, startMs=0),))
    for cap in (5, _headerLen() - 5, _headerLen() + 5, _headerLen() + 20):
        out = formatTranscript(result, maxTranscriptChars=cap)
        assert len(out) == cap, f"cap={cap}: len(out)={len(out)}"


# ============================================================================
# Header counted inside the cap — output never exceeds cap
# ============================================================================


def testHeaderIsCountedInsideTheCap() -> None:
    """The output length never exceeds maxTranscriptChars (header included).

    Returns:
        None
    """
    body = "z" * 3000
    result = _result((_segment(body, startMs=0),))
    for cap in (_headerLen() + 30, _headerLen() + 99, _headerLen() + 500):
        out = formatTranscript(result, maxTranscriptChars=cap)
        assert len(out) <= cap
        assert out.startswith(UNTRUSTED_TRANSCRIPT_HEADER)


# ============================================================================
# Purity / non-raising contract
# ============================================================================


def testFormatterDoesNotRaiseOnErrorResultWithEmptySegments() -> None:
    """An ERROR result with empty segments yields the sentinel (no raise).

    The formatter is segment-driven and pure; the service, not this function,
    gates ERROR handling.

    Returns:
        None
    """
    result = TranscriptionResult(status=STTResultStatus.ERROR, segments=())
    out = formatTranscript(result, maxTranscriptChars=10000)
    assert out == "[No speech detected]"
