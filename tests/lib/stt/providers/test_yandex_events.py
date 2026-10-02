"""Golden-data unit tests for lib.stt.providers.yandex_events (§7.3 event parser).

Covers (per ``docs/design/lib-stt-v1.md`` §7.3 / §9):
- A single final event → FINAL with one segment.
- Multiple final events → FINAL with several segments, sorted by start time.
- Top-alternative selection (only ``alternatives[0]`` is consumed).
- ``int64`` timestamps as integers AND decimal strings (protobuf JSON).
- Per-word text + millisecond ranges parsed into TranscriptionWord.
- ``finalRefinement`` replaces the raw final text by ``finalIndex`` (no duplicate).
- Non-final events (``partial`` / ``status_code``) are ignored.
- Out-of-time-order finals are sorted by start time before return.
- No-speech outcomes: an empty/whitespace stream and all-empty finals → NO_SPEECH.
- Result-body cap (§8.1): over-cap → ERROR/PROTOCOL_ERROR; at-cap → parses.
- Malformed input never raises: invalid UTF-8, broken JSON, trailing garbage, a
  non-numeric timestamp, a wrong-typed field all → ERROR/PROTOCOL_ERROR.
- Defensive compatibility: events without the ``result`` wrapper still parse.

Per load-bearing contract #4 (§7.3 / §10(a)), committed aurumentation golden
fixtures record live SpeechKit responses and verify the ``getRecognition``
streaming-JSON framing, including its ``result`` wrapper. Bare-envelope parsing
is retained only as defensive compatibility for variant or future input.
"""

import json
from typing import Dict, List, Optional

import pytest

from lib.stt.models import STTAttributionType, STTErrorCode, STTResultStatus, TranscriptionWord
from lib.stt.providers.yandex_events import (
    DEFAULT_MAX_RESULT_BYTES,
    parseRecognitionEvents,
)

# Cap large enough that no golden fixture here is meant to hit the result-body
# limit; cap-specific tests pass the limit explicitly.
_ROOMY_CAP: int = 10 * 1024 * 1024


# ============================================================================
# Fixture builders — construct the verified streaming-JSON shape.
#
# Each *_event() helper returns the StreamingResponse EVENT PAYLOAD (the inner
# object holding the oneof Event). _wire() wraps each payload in {"result": ...}
# (the recorded §7.3 ``result.final`` shape), JSON-encodes them, and joins with
# newlines into the event stream. Pass wrapped=False for defensive-compatibility
# cases.
# ============================================================================


def _wire(eventPayloads: List[Dict[str, object]], *, wrapped: bool = True) -> bytes:
    """Serialize event payloads into the verified streaming-JSON byte stream.

    Args:
        eventPayloads: The inner StreamingResponse event objects (each carrying
            one oneof Event such as ``final`` / ``finalRefinement`` / ``partial``).
        wrapped: When True (default), wrap each payload in ``{"result": ...}`` per
            the recorded §7.3 shape. When False, emit payloads bare for the
            defensive-compatibility test.

    Returns:
        bytes: The newline-joined, UTF-8 encoded event stream.
    """
    chunks: List[str] = []
    for payload in eventPayloads:
        event = {"result": payload} if wrapped else payload
        chunks.append(json.dumps(event))
    return "\n".join(chunks).encode("utf-8")


def _finalEvent(
    text: str,
    startMs: object,
    endMs: object,
    words: Optional[List[Dict[str, object]]] = None,
    extraAlternatives: Optional[List[Dict[str, object]]] = None,
    channelTag: Optional[object] = None,
    includeChannelTag: bool = False,
) -> Dict[str, object]:
    """Build a ``final`` StreamingResponse event payload.

    Args:
        text: The first alternative's text.
        startMs: The first alternative's start time (int or decimal string).
        endMs: The first alternative's end time (int or decimal string).
        words: Optional words list for the first alternative.
        extraAlternatives: Additional (lower-ranked) alternatives to assert that
            only the first is consumed.
        channelTag: Deprecated final-level channel tag used to verify that the
            parser ignores it.
        includeChannelTag: Whether to emit the deprecated field even when its
            value is null.

    Returns:
        Dict[str, object]: The ``{"final": {"alternatives": [...]}}`` payload.
    """
    firstAlternative: Dict[str, object] = {"text": text, "startTimeMs": startMs, "endTimeMs": endMs}
    if words is not None:
        firstAlternative["words"] = words
    alternatives: List[Dict[str, object]] = [firstAlternative]
    if extraAlternatives is not None:
        alternatives.extend(extraAlternatives)
    final: Dict[str, object] = {"alternatives": alternatives}
    if channelTag is not None or includeChannelTag:
        final["channelTag"] = channelTag
    return {"final": final}


def _word(text: str, startMs: object, endMs: object) -> Dict[str, object]:
    """Build a single Word object.

    Args:
        text: The word text.
        startMs: The word start time (int or decimal string).
        endMs: The word end time (int or decimal string).

    Returns:
        Dict[str, object]: The ``{"text", "startTimeMs", "endTimeMs"}`` word.
    """
    return {"text": text, "startTimeMs": startMs, "endTimeMs": endMs}


def _refinementEvent(
    finalIndex: object, text: str, words: Optional[List[Dict[str, object]]] = None
) -> Dict[str, object]:
    """Build a ``finalRefinement`` StreamingResponse event payload.

    Args:
        finalIndex: The index of the final this refinement replaces (int or
            decimal string, mirroring protobuf int64 JSON).
        text: The normalized text for the first normalized alternative.
        words: Optional normalized words for the first alternative.

    Returns:
        Dict[str, object]: The ``{"finalRefinement": {...}}`` payload.
    """
    normalizedAlternative: Dict[str, object] = {"text": text}
    if words is not None:
        normalizedAlternative["words"] = words
    return {
        "finalRefinement": {
            "finalIndex": finalIndex,
            "normalizedText": {"alternatives": [normalizedAlternative]},
        }
    }


def _partialEvent(text: str) -> Dict[str, object]:
    """Build a ``partial`` StreamingResponse event payload (must be ignored).

    Args:
        text: The partial hypothesis text.

    Returns:
        Dict[str, object]: The ``{"partial": {"alternatives": [...]}}`` payload.
    """
    return {"partial": {"alternatives": [{"text": text}]}}


def _statusEvent(message: str) -> Dict[str, object]:
    """Build a ``statusCode`` keep-alive event payload (must be ignored).

    Args:
        message: The status message text.

    Returns:
        Dict[str, object]: The ``{"statusCode": {...}}`` payload.
    """
    return {"statusCode": {"codeType": "WORKING", "message": message}}


# ============================================================================
# Basic final parsing
# ============================================================================


def testSingleFinalEventYieldsFinalResult() -> None:
    """A single final event parses to FINAL with one segment (text + ms range).

    Returns:
        None
    """
    body = _wire([_finalEvent("hello world", startMs=0, endMs=3000, words=[_word("hello", 0, 1500)])])
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.FINAL
    assert result.errorCode is None
    assert len(result.segments) == 1
    segment = result.segments[0]
    assert segment.text == "hello world"
    assert segment.startMs == 0
    assert segment.endMs == 3000
    assert segment.words == (TranscriptionWord(text="hello", startMs=0, endMs=1500),)


def testMultipleFinalEventsYieldSortedSegments() -> None:
    """Multiple final events yield one segment each, sorted by start time.

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("first", startMs=0, endMs=1000),
            _finalEvent("second", startMs=2000, endMs=3000),
            _finalEvent("third", startMs=5000, endMs=6000),
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.FINAL
    assert [segment.text for segment in result.segments] == ["first", "second", "third"]
    assert [segment.startMs for segment in result.segments] == [0, 2000, 5000]


def testTopAlternativeSelectionIgnoresLowerRanked() -> None:
    """Only alternatives[0] is consumed; lower-ranked alternatives are dropped.

    Alternatives are competing hypotheses for the same frame, not segments.

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent(
                "primary hypothesis",
                startMs=100,
                endMs=200,
                extraAlternatives=[
                    {"text": "secondary hypothesis", "startTimeMs": 999, "endTimeMs": 999},
                    {"text": "tertiary hypothesis", "startTimeMs": 888, "endTimeMs": 888},
                ],
            )
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.FINAL
    assert len(result.segments) == 1
    assert result.segments[0].text == "primary hypothesis"
    assert result.segments[0].startMs == 100


# ============================================================================
# channelTag — canonical envelope metadata; final-level field is ignored
# ============================================================================


def testCanonicalChannelTagPropagatesToSegment() -> None:
    """Default mode preserves canonical tags as channel metadata, not speakers.

    Returns:
        None
    """
    final = _finalEvent("left channel", startMs=0, endMs=1000)
    final["channelTag"] = "left"

    result = parseRecognitionEvents(_wire([final]), maxResultBytes=_ROOMY_CAP)

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].attributionTag == "left"
    assert result.attributionType is STTAttributionType.CHANNEL


def testCanonicalChannelTagWinsOverDeprecatedFinalTag() -> None:
    """A non-empty canonical channelTag takes precedence over the deprecated tag.

    Regression: the final-level value previously overwrote the canonical envelope
    value even when both were valid non-empty strings.

    Returns:
        None
    """
    final = _finalEvent("canonical wins", startMs=0, endMs=1000, channelTag="deprecated")
    final["channelTag"] = "canonical"

    result = parseRecognitionEvents(_wire([final]), maxResultBytes=_ROOMY_CAP)

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].attributionTag == "canonical"


@pytest.mark.parametrize("channelTag, includeChannelTag", [(None, True), ("", False)])
def testDeprecatedFinalChannelTagIsIgnored(channelTag: Optional[str], includeChannelTag: bool) -> None:
    """Deprecated final tags never supply attribution in ordinary mode.

    Args:
        channelTag: The null or empty deprecated channel tag value.
        includeChannelTag: Whether to emit an explicit null deprecated field.

    Returns:
        None
    """
    final = _finalEvent(
        "untagged legacy fallback",
        startMs=0,
        endMs=1000,
        channelTag=channelTag,
        includeChannelTag=includeChannelTag,
    )

    result = parseRecognitionEvents(_wire([final]), maxResultBytes=_ROOMY_CAP)

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].attributionTag is None


def testRefinementPreservesAttributionTag() -> None:
    """A finalRefinement keeps the selected attribution tag while replacing text.

    Returns:
        None
    """
    final = _finalEvent("raw", startMs=0, endMs=1000)
    final["channelTag"] = "right"

    result = parseRecognitionEvents(
        _wire([final, _refinementEvent(finalIndex=0, text="normalized")]), maxResultBytes=_ROOMY_CAP
    )

    assert result.segments[0].text == "normalized"
    assert result.segments[0].attributionTag == "right"


def testDeprecatedFinalChannelTagDoesNotCreateOrdinaryAttribution() -> None:
    """A deprecated final-level tag cannot create ordinary attribution.

    Returns:
        None
    """
    final = _finalEvent("legacy channel", startMs=0, endMs=1000, channelTag="legacy")

    result = parseRecognitionEvents(_wire([final]), maxResultBytes=_ROOMY_CAP)

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].attributionTag is None


@pytest.mark.parametrize("canonicalTag", [None, ""])
def testNullOrEmptyCanonicalTagDoesNotUseDeprecatedFinalTag(canonicalTag: Optional[str]) -> None:
    """Null and empty canonical tags remain unattributed in ordinary mode.

    Args:
        canonicalTag: The explicit null or empty canonical envelope tag.

    Returns:
        None
    """
    final = _finalEvent("legacy fallback", startMs=0, endMs=1000, channelTag="legacy")
    final["channelTag"] = canonicalTag

    result = parseRecognitionEvents(_wire([final]), maxResultBytes=_ROOMY_CAP)

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].attributionTag is None


@pytest.mark.parametrize("canonicalTag", [None, ""])
def testSpeakerLabelingNullOrEmptyCanonicalTagDoesNotUseDeprecatedFinalTag(canonicalTag: Optional[str]) -> None:
    """Speaker mode does not use a valid deprecated tag after null or empty canonical tags.

    Args:
        canonicalTag: The explicit null or empty canonical envelope tag.

    Returns:
        None
    """
    final = _finalEvent("no speaker fallback", startMs=0, endMs=1000, channelTag="legacy")
    final["channelTag"] = canonicalTag

    result = parseRecognitionEvents(
        _wire([final]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=True,
    )

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].attributionTag is None


def testSpeakerLabelingMapsCanonicalEnvelopeTagToUnifiedAttribution() -> None:
    """Speaker mode maps a canonical tag to unified attribution without a cursor.

    Returns:
        None
    """
    final = _finalEvent("recognized speaker", startMs=0, endMs=1000, channelTag="deprecated")
    final["channelTag"] = "speaker-1"
    result = parseRecognitionEvents(_wire([final]), maxResultBytes=_ROOMY_CAP, speakerLabelingRequested=True)

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].attributionTag == "speaker-1"
    assert result.attributionType is STTAttributionType.SPEAKER


def testSpeakerLabelingDoesNotUseDeprecatedFinalChannelTag() -> None:
    """A deprecated final-level tag cannot create a speaker label.

    Returns:
        None
    """
    final = _finalEvent("not a speaker", startMs=0, endMs=1000, channelTag="legacy")

    result = parseRecognitionEvents(_wire([final]), maxResultBytes=_ROOMY_CAP, speakerLabelingRequested=True)

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].attributionTag is None


@pytest.mark.parametrize("channelTag, includeChannelTag", [(None, False), (None, True), ("", False)])
def testSpeakerLabelingMissingNullOrEmptyCanonicalTagLeavesAttributionUnset(
    channelTag: Optional[str], includeChannelTag: bool
) -> None:
    """Missing, null, and empty canonical tags leave both fields unset in speaker mode.

    Args:
        channelTag: The null or empty canonical tag value.
        includeChannelTag: Whether to emit an explicit null canonical field.

    Returns:
        None
    """
    final = _finalEvent("untagged", startMs=0, endMs=1000)
    if channelTag is not None or includeChannelTag:
        final["channelTag"] = channelTag

    result = parseRecognitionEvents(_wire([final]), maxResultBytes=_ROOMY_CAP, speakerLabelingRequested=True)

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].attributionTag is None


@pytest.mark.parametrize("canonicalTag, expectedTag", [(123, "123"), (False, "False"), ([], "[]"), ({}, "{}")])
@pytest.mark.parametrize("speakerLabelingRequested", [False, True])
def testCanonicalJsonTagValuesStringify(canonicalTag: object, expectedTag: str, speakerLabelingRequested: bool) -> None:
    """Canonical number, boolean, list, and object tags stringify without errors.

    Args:
        canonicalTag: A non-string canonical JSON tag value.
        expectedTag: Its required string representation.
        speakerLabelingRequested: Whether the parser is in speaker-label mode.

    Returns:
        None
    """
    final = _finalEvent("stringified tag", startMs=0, endMs=1000)
    final["channelTag"] = canonicalTag
    if speakerLabelingRequested:
        final["audioCursors"] = {"finalIndex": 0}

    result = parseRecognitionEvents(
        _wire([final]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=speakerLabelingRequested,
    )

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].attributionTag == expectedTag
    assert result.segments[0].attributionTag == expectedTag


@pytest.mark.parametrize("deprecatedTag", [123, False, [], {}])
@pytest.mark.parametrize("speakerLabelingRequested", [False, True])
def testDeprecatedFinalTagNeverAffectsCanonicalAttribution(
    deprecatedTag: object, speakerLabelingRequested: bool
) -> None:
    """Valid and malformed deprecated tags are never read by the parser.

    Args:
        deprecatedTag: A valid or malformed deprecated final-level tag value.
        speakerLabelingRequested: Whether a valid canonical tag is mapped to a
            speaker label instead of ordinary channel metadata.

    Returns:
        None
    """
    final = _finalEvent(
        "ignored deprecated tag", startMs=0, endMs=1000, channelTag=deprecatedTag, includeChannelTag=True
    )
    final["channelTag"] = "canonical"
    if speakerLabelingRequested:
        final["audioCursors"] = {"finalIndex": 0}

    result = parseRecognitionEvents(
        _wire([final]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=speakerLabelingRequested,
    )

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].attributionTag == "canonical"


def testRefinementPreservesSpeakerAttributionTag() -> None:
    """A finalRefinement keeps the selected attribution in speaker mode.

    Returns:
        None
    """
    final = _finalEvent("raw", startMs=0, endMs=1000)
    final["channelTag"] = "speaker-2"
    final["audioCursors"] = {"finalIndex": 0}
    refinement = _refinementEvent(finalIndex=0, text="normalized")
    refinement["channelTag"] = "speaker-2"

    result = parseRecognitionEvents(
        _wire([final, refinement]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=True,
    )

    assert result.segments[0].text == "normalized"
    assert result.segments[0].attributionTag == "speaker-2"


@pytest.mark.parametrize(
    "canonicalTag, expectedTag", [(7, "7"), (True, "True"), (["a"], "['a']"), ({"a": 1}, "{'a': 1}")]
)
def testSpeakerRefinementUsesStringifiedCanonicalTagKey(canonicalTag: object, expectedTag: str) -> None:
    """Speaker refinements correlate through the stringified canonical tag.

    Args:
        canonicalTag: A non-string canonical tag supplied on final and refinement.
        expectedTag: The required canonical string form.

    Returns:
        None
    """
    final = _finalEvent("raw", startMs=0, endMs=1000)
    final["channelTag"] = canonicalTag
    final["audioCursors"] = {"finalIndex": 0}
    refinement = _refinementEvent(finalIndex=0, text="normalized")
    refinement["channelTag"] = canonicalTag

    result = parseRecognitionEvents(
        _wire([final, refinement]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=True,
    )

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].text == "normalized"
    assert result.segments[0].attributionTag == expectedTag
    assert result.segments[0].attributionTag == expectedTag


@pytest.mark.parametrize("includeAudioCursors", [False, True])
def testSpeakerLabelingWithoutUsableCursorRetainsAttributionAndBareRefinement(
    includeAudioCursors: bool,
) -> None:
    """Speaker mode retains wire attribution and bare refinement without a cursor.

    A missing cursor and an explicit null cursor cannot form the composite
    ``(canonicalTag, finalIndex)`` correlation key. Both must therefore use
    bare-index refinement as a compatibility fallback. The canonical envelope
    tag remains independent wire attribution.

    Args:
        includeAudioCursors: Whether to emit ``audioCursors.finalIndex`` as null
            instead of omitting audio-cursor metadata entirely.

    Returns:
        None
    """
    final = _finalEvent("raw", startMs=0, endMs=1000)
    final["channelTag"] = "speaker-2"
    if includeAudioCursors:
        final["audioCursors"] = {"finalIndex": None}

    result = parseRecognitionEvents(
        _wire([final, _refinementEvent(finalIndex=0, text="normalized")]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=True,
    )

    assert result.segments[0].text == "normalized"
    assert result.segments[0].attributionTag == "speaker-2"


def testTaggedSpeakerRefinementDoesNotCrossApplyToUntaggedCursorlessFinal() -> None:
    """A tagged refinement cannot replace an untagged cursorless final at its bare index.

    A speaker-tagged final may use a provider-local cursor index that coincides
    with the stream-order index of an untagged cursorless final. Tagged
    refinements must remain in the composite speaker map and therefore only
    replace the tagged final.

    Returns:
        None
    """
    untaggedFinal = _finalEvent("untagged raw", startMs=0, endMs=1000)
    taggedFinal = _finalEvent("tagged raw", startMs=1200, endMs=2200)
    taggedFinal["channelTag"] = "speaker-a"
    taggedFinal["audioCursors"] = {"finalIndex": 0}
    taggedRefinement = _refinementEvent(finalIndex=0, text="tagged normalized")
    taggedRefinement["channelTag"] = "speaker-a"

    result = parseRecognitionEvents(
        _wire([untaggedFinal, taggedFinal, taggedRefinement]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=True,
    )

    assert [(segment.text, segment.attributionTag) for segment in result.segments] == [
        ("untagged raw", None),
        ("tagged normalized", "speaker-a"),
    ]


@pytest.mark.parametrize("speakerLabelingRequested", [False, True])
@pytest.mark.parametrize("malformedCursor", [False, 0, "cursor", []])
def testMalformedCursorContainerYieldsProtocolError(speakerLabelingRequested: bool, malformedCursor: object) -> None:
    """A non-null, non-object audioCursors container poisons the stream atomically.

    Regression: malformed cursor containers previously collapsed into the same
    unattributed fallback as an absent or null cursor. Only absence/null remains
    legacy-compatible; a malformed supplied container must not reach either
    refinement map.

    Args:
        speakerLabelingRequested: Whether to exercise ordinary or speaker mode.
        malformedCursor: A non-null JSON value that is not an audio-cursor object.

    Returns:
        None
    """
    final = _finalEvent("raw", startMs=0, endMs=1000)
    final["channelTag"] = "speaker-1"
    final["audioCursors"] = malformedCursor

    result = parseRecognitionEvents(
        _wire([final]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=speakerLabelingRequested,
    )

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR
    assert result.segments == ()


@pytest.mark.parametrize("speakerLabelingRequested", [False, True])
@pytest.mark.parametrize("invalidIndex", [0.5, -1, True, "0.5", "-1", " 0", "+0", "00", "0 ", [], {}])
def testInvalidFinalCursorIndexYieldsProtocolError(speakerLabelingRequested: bool, invalidIndex: object) -> None:
    """A supplied final cursor index must be a canonical non-negative protobuf integer.

    Regression: fractional, negative, and noncanonical string cursor values were
    coerced or ignored, allowing an invalid final identity into speaker or ordinary
    refinement correlation.

    Args:
        speakerLabelingRequested: Whether to exercise ordinary or speaker mode.
        invalidIndex: A malformed non-null final cursor index.

    Returns:
        None
    """
    final = _finalEvent("raw", startMs=0, endMs=1000)
    final["channelTag"] = "speaker-1"
    final["audioCursors"] = {"finalIndex": invalidIndex}

    result = parseRecognitionEvents(
        _wire([final]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=speakerLabelingRequested,
    )

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR
    assert result.segments == ()


@pytest.mark.parametrize("speakerLabelingRequested", [False, True])
@pytest.mark.parametrize("invalidIndex", [0.5, -1, True, "0.5", "-1", " 0", "+0", "00", "0 ", [], {}])
def testInvalidRefinementIndexYieldsProtocolErrorBeforeMapInsertion(
    speakerLabelingRequested: bool, invalidIndex: object
) -> None:
    """A malformed refinement index cannot enter ordinary or speaker maps.

    Args:
        speakerLabelingRequested: Whether to exercise ordinary or speaker mode.
        invalidIndex: A malformed non-null refinement index.

    Returns:
        None
    """
    final = _finalEvent("raw", startMs=0, endMs=1000)
    if speakerLabelingRequested:
        final["channelTag"] = "speaker-1"
        final["audioCursors"] = {"finalIndex": 0}
    refinement = _refinementEvent(finalIndex=invalidIndex, text="must not replace")
    if speakerLabelingRequested:
        refinement["channelTag"] = "speaker-1"

    result = parseRecognitionEvents(
        _wire([final, refinement]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=speakerLabelingRequested,
    )

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR
    assert result.segments == ()


@pytest.mark.parametrize("zeroIndex", [0, "0"])
def testCanonicalZeroCursorAndRefinementIndicesRemainValid(zeroIndex: object) -> None:
    """Exact zero remains valid for protobuf numeric and string representations.

    Args:
        zeroIndex: A canonical protobuf JSON representation of zero.

    Returns:
        None
    """
    final = _finalEvent("raw", startMs=0, endMs=1000)
    final["channelTag"] = "speaker-1"
    final["audioCursors"] = {"finalIndex": zeroIndex}
    refinement = _refinementEvent(finalIndex=zeroIndex, text="normalized")
    refinement["channelTag"] = "speaker-1"

    result = parseRecognitionEvents(
        _wire([final, refinement]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=True,
    )

    assert result.status is STTResultStatus.FINAL
    assert [(segment.text, segment.attributionTag) for segment in result.segments] == [("normalized", "speaker-1")]


def testSpeakerRefinementsWithSharedFinalIndicesRemainCorrelated() -> None:
    """Interleaved speakers retain refinements sharing the same finalIndex.

    Speaker-labeled streams number finals independently per canonical envelope
    channelTag. Both speakers therefore use finalIndex 0 here. Before the
    speaker-aware correlation fix, bare-index storage let speaker-b's refinement
    replace speaker-a's text while leaving speaker-b's raw text unchanged.

    Returns:
        None
    """
    speakerAFinal = _finalEvent("alpha raw", startMs=0, endMs=1000, words=[_word("alpha", 0, 1000)])
    speakerAFinal["channelTag"] = "speaker-a"
    speakerAFinal["audioCursors"] = {"finalIndex": 0}
    speakerBFinal = _finalEvent("bravo raw", startMs=1200, endMs=2200, words=[_word("bravo", 1200, 2200)])
    speakerBFinal["channelTag"] = "speaker-b"
    speakerBFinal["audioCursors"] = {"finalIndex": 0}
    speakerARefinement = _refinementEvent(finalIndex=0, text="Alpha.", words=[_word("Alpha.", 0, 1000)])
    speakerARefinement["channelTag"] = "speaker-a"
    speakerBRefinement = _refinementEvent(finalIndex=0, text="Bravo.", words=[_word("Bravo.", 1200, 2200)])
    speakerBRefinement["channelTag"] = "speaker-b"

    result = parseRecognitionEvents(
        _wire([speakerAFinal, speakerBFinal, speakerARefinement, speakerBRefinement]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=True,
    )

    assert [(segment.text, segment.attributionTag) for segment in result.segments] == [
        ("Alpha.", "speaker-a"),
        ("Bravo.", "speaker-b"),
    ]
    assert [segment.words for segment in result.segments] == [
        (TranscriptionWord(text="Alpha.", startMs=0, endMs=1000),),
        (TranscriptionWord(text="Bravo.", startMs=1200, endMs=2200),),
    ]


def testSpeakerRefinementDoesNotCrossApplyWhenOtherSpeakerHasNoRefinement() -> None:
    """A tagged refinement cannot replace another tagged speaker's raw final.

    Args:
        None

    Returns:
        None
    """
    speakerAFinal = _finalEvent("alpha raw", startMs=0, endMs=1000)
    speakerAFinal["channelTag"] = "speaker-a"
    speakerAFinal["audioCursors"] = {"finalIndex": 0}
    speakerBFinal = _finalEvent("bravo raw", startMs=1200, endMs=2200)
    speakerBFinal["channelTag"] = "speaker-b"
    speakerBFinal["audioCursors"] = {"finalIndex": 0}
    speakerBRefinement = _refinementEvent(finalIndex=0, text="Bravo.")
    speakerBRefinement["channelTag"] = "speaker-b"

    result = parseRecognitionEvents(
        _wire([speakerAFinal, speakerBFinal, speakerBRefinement]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=True,
    )

    assert [(segment.text, segment.attributionTag) for segment in result.segments] == [
        ("alpha raw", "speaker-a"),
        ("Bravo.", "speaker-b"),
    ]


def testTaggedSegmentsSortByStartTime() -> None:
    """Segments retain their tags after sorting into chronological order.

    Returns:
        None
    """
    late = _finalEvent("right later", startMs=2000, endMs=3000)
    late["channelTag"] = "right"
    early = _finalEvent("left earlier", startMs=0, endMs=1000)
    early["channelTag"] = "left"

    result = parseRecognitionEvents(_wire([late, early]), maxResultBytes=_ROOMY_CAP)

    assert [(segment.text, segment.attributionTag) for segment in result.segments] == [
        ("left earlier", "left"),
        ("right later", "right"),
    ]


# ============================================================================
# Timestamps — int and decimal-string (protobuf JSON int64)
# ============================================================================


def testIntegerTimestampsParse() -> None:
    """Integer timestamp fields parse directly to millisecond ints.

    Returns:
        None
    """
    body = _wire([_finalEvent("text", startMs=1500, endMs=2700)])
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.segments[0].startMs == 1500
    assert result.segments[0].endMs == 2700


def testDecimalStringTimestampsParse() -> None:
    """Timestamp fields encoded as decimal strings (protobuf int64 JSON) parse.

    Returns:
        None
    """
    body = _wire([_finalEvent("text", startMs="1500", endMs="2700")])
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.segments[0].startMs == 1500
    assert result.segments[0].endMs == 2700


def testWordTimestampsAsStringsAndInts() -> None:
    """Per-word timestamps accept both integer and decimal-string encodings.

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent(
                "one two",
                startMs=0,
                endMs=2000,
                words=[_word("one", 0, "1000"), _word("two", "1000", 2000)],
            )
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.segments[0].words == (
        TranscriptionWord(text="one", startMs=0, endMs=1000),
        TranscriptionWord(text="two", startMs=1000, endMs=2000),
    )


# ============================================================================
# finalRefinement — replaces raw text by finalIndex, no duplicate
# ============================================================================


def testFinalRefinementReplacesRawText() -> None:
    """A matching finalRefinement replaces the raw final text (no duplicate).

    The raw "i c" final is replaced by the normalized "I see" refinement, and the
    raw text does NOT also appear in the output.

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("i c", startMs=0, endMs=1000),
            _refinementEvent(finalIndex=0, text="I see."),
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.FINAL
    assert [segment.text for segment in result.segments] == ["I see."]
    assert "i c" not in [segment.text for segment in result.segments]


def testFinalRefinementReplacesWordsWhenProvided() -> None:
    """A refinement carrying words replaces both text and words (alignment kept).

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("u s a", startMs=100, endMs=900, words=[_word("u", 100, 300)]),
            _refinementEvent(finalIndex=0, text="USA", words=[_word("USA", 100, 900)]),
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    segment = result.segments[0]
    assert segment.text == "USA"
    assert segment.words == (TranscriptionWord(text="USA", startMs=100, endMs=900),)


def testFinalRefinementWithoutWordsKeepsRawWords() -> None:
    """A refinement carrying only text keeps the raw final's words unchanged.

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("one two", startMs=0, endMs=1000, words=[_word("one", 0, 500)]),
            _refinementEvent(finalIndex=0, text="one two."),  # no words provided
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    segment = result.segments[0]
    assert segment.text == "one two."
    assert segment.words == (TranscriptionWord(text="one", startMs=0, endMs=500),)


def testFinalRefinementKeepsRawTimeRange() -> None:
    """A refinement does not change the segment ms range (same time frame).

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("raw", startMs=4000, endMs=8000),
            _refinementEvent(finalIndex=0, text="normalized"),
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.segments[0].startMs == 4000
    assert result.segments[0].endMs == 8000


def testFinalRefinementTargetsFinalByIndex() -> None:
    """A refinement applies only to its matching finalIndex, leaving others raw.

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("raw one", startMs=0, endMs=1000),
            _finalEvent("raw two", startMs=2000, endMs=3000),
            # Refine ONLY the second final (index 1).
            _refinementEvent(finalIndex=1, text="normalized two"),
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert [segment.text for segment in result.segments] == ["raw one", "normalized two"]


def testRefinementBeforeFinalStillApplies() -> None:
    """A refinement is applied by index regardless of stream order vs its final.

    Returns:
        None
    """
    body = _wire(
        [
            _refinementEvent(finalIndex=0, text="normalized"),
            _finalEvent("raw", startMs=0, endMs=1000),
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert [segment.text for segment in result.segments] == ["normalized"]


def testEmptyFinalConsumesIndexPreservingRefinementAlignment() -> None:
    """An empty-text final still consumes an index, keeping refinement alignment.

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("", startMs=0, endMs=500),  # index 0 — empty, filtered
            _finalEvent("second", startMs=600, endMs=900),  # index 1
            _refinementEvent(finalIndex=1, text="second normalized"),
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert [segment.text for segment in result.segments] == ["second normalized"]


# ============================================================================
# Non-final events ignored
# ============================================================================


def testPartialAndStatusEventsAreIgnored() -> None:
    """partial and statusCode events are ignored; only finals contribute.

    Returns:
        None
    """
    body = _wire(
        [
            _statusEvent("working"),
            _partialEvent("interim hypothesis"),
            _finalEvent("final text", startMs=0, endMs=1000),
            _partialEvent("another interim"),
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.FINAL
    assert [segment.text for segment in result.segments] == ["final text"]


# ============================================================================
# Out-of-time-order finals sorted by start time
# ============================================================================


def testOutOfOrderFinalsSortedByStartTime() -> None:
    """Finals emitted with non-monotonic start times are sorted before return.

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("c-late", startMs=8000, endMs=9000),
            _finalEvent("a-early", startMs=1000, endMs=2000),
            _finalEvent("b-mid", startMs=4000, endMs=5000),
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert [segment.text for segment in result.segments] == ["a-early", "b-mid", "c-late"]
    assert [segment.startMs for segment in result.segments] == [1000, 4000, 8000]


# ============================================================================
# NO_SPEECH outcomes
# ============================================================================


def testEmptyByteStreamYieldsNoSpeech() -> None:
    """An empty event stream yields NO_SPEECH (no final segments).

    Returns:
        None
    """
    result = parseRecognitionEvents(b"", maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.NO_SPEECH
    assert result.segments == ()
    assert result.errorCode is None


def testSpeakerNoSpeechResultKeepsSpeakerAttributionType() -> None:
    """Speaker-label requests retain their result-level role without segments.

    Returns:
        None
    """
    result = parseRecognitionEvents(b"", maxResultBytes=_ROOMY_CAP, speakerLabelingRequested=True)
    assert result.status is STTResultStatus.NO_SPEECH
    assert result.attributionType is STTAttributionType.SPEAKER


def testWhitespaceOnlyStreamYieldsNoSpeech() -> None:
    """A whitespace-only stream (no objects) yields NO_SPEECH.

    Returns:
        None
    """
    result = parseRecognitionEvents(b"  \n\t \r\n ", maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.NO_SPEECH


def testAllEmptyFinalsYieldNoSpeech() -> None:
    """Finals that are all empty-text yield NO_SPEECH (no non-empty segment).

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("", startMs=0, endMs=1000),
            _finalEvent("   ", startMs=2000, endMs=3000),
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.NO_SPEECH
    assert result.segments == ()


def testOnlyPartialsYieldNoSpeech() -> None:
    """A stream with only partial (non-final) events yields NO_SPEECH.

    Returns:
        None
    """
    body = _wire([_partialEvent("just a partial"), _statusEvent("done")])
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.NO_SPEECH


# ============================================================================
# Result-body cap (§8.1) — owned and enforced here
# ============================================================================


def testOverCapBytesYieldProtocolError() -> None:
    """A body whose byte length exceeds maxResultBytes yields PROTOCOL_ERROR.

    Returns:
        None
    """
    body = _wire([_finalEvent("text", startMs=0, endMs=1)])
    assert len(body) > 4
    result = parseRecognitionEvents(body, maxResultBytes=4)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR
    assert result.segments == ()


def testAtCapBytesParseSuccessfully() -> None:
    """A body whose byte length equals maxResultBytes parses (inclusive cap).

    Returns:
        None
    """
    body = _wire([_finalEvent("text", startMs=0, endMs=1)])
    result = parseRecognitionEvents(body, maxResultBytes=len(body))
    assert result.status is STTResultStatus.FINAL
    assert [segment.text for segment in result.segments] == ["text"]


def testDefaultMaxResultBytesMatchesSpec() -> None:
    """The module-level default cap equals the §8.1 value (5 MiB).

    Returns:
        None
    """
    assert DEFAULT_MAX_RESULT_BYTES == 5_242_880


# ============================================================================
# Malformed input — never raises, returns PROTOCOL_ERROR
# ============================================================================


def testInvalidUtf8YieldsProtocolError() -> None:
    """Invalid UTF-8 bytes yield PROTOCOL_ERROR (strict decode), never raise.

    Returns:
        None
    """
    result = parseRecognitionEvents(b'{"result": {"final": \xff}}', maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


def testBrokenJsonYieldsProtocolError() -> None:
    """Malformed JSON yields PROTOCOL_ERROR, never raise.

    Returns:
        None
    """
    result = parseRecognitionEvents(b'{"result": {"final": ', maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


def testTrailingGarbageYieldsProtocolError() -> None:
    """Valid objects followed by non-whitespace garbage yield PROTOCOL_ERROR.

    Returns:
        None
    """
    payload = json.dumps({"result": {"final": {"alternatives": [{"text": "x", "startTimeMs": 0, "endTimeMs": 1}]}}})
    body = (payload + " GARBAGE").encode("utf-8")
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


def testTopLevelArrayIsGarbage() -> None:
    """A single JSON array document (not consecutive objects) is rejected as garbage.

    §7.3 specifies consecutive JSON event objects, not one JSON document.

    Returns:
        None
    """
    body = b'[{"result": {"final": {"alternatives": [{"text": "x", "startTimeMs": 0, "endTimeMs": 1}]}}}]'
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


def testNonObjectEventYieldsProtocolError() -> None:
    """A top-level JSON value that is not an object yields PROTOCOL_ERROR.

    Returns:
        None
    """
    body = b'"just a string"'
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


def testMalformedTimestampYieldsProtocolError() -> None:
    """A non-numeric timestamp value yields PROTOCOL_ERROR (atomic stream).

    Returns:
        None
    """
    body = _wire([_finalEvent("text", startMs="not-a-number", endMs=1000)])
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


def testNonStringTextYieldsProtocolError() -> None:
    """A non-string ``text`` field yields PROTOCOL_ERROR, never raise.

    Returns:
        None
    """
    body = b'{"result": {"final": {"alternatives": [{"text": 123, "startTimeMs": 0, "endTimeMs": 1}]}}}'
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


def testGarbageBytesNeverRaise() -> None:
    """Arbitrary garbage bytes yield PROTOCOL_ERROR and never raise.

    Returns:
        None
    """
    result = parseRecognitionEvents(b"\x00\x01\x02\xff\xfe garbage \x00", maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


def testSingleMalformedEventPoisonsWholeStream() -> None:
    """One malformed event among valid ones yields PROTOCOL_ERROR (§7.4 atomicity).

    Returns:
        None
    """
    good = json.dumps({"result": {"final": {"alternatives": [{"text": "good", "startTimeMs": 0, "endTimeMs": 1}]}}})
    bad = b'{"result": {"final": {"alternatives": [{"text": "bad", "startTimeMs": "x", "endTimeMs": 1}]}}}'
    body = good.encode("utf-8") + b"\n" + bad
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


# ============================================================================
# Bare-envelope defensive compatibility (load-bearing contract #4)
# ============================================================================


def testBareEnvelopeWithoutResultWrapperStillParses() -> None:
    """Events without the top-level ``result`` wrapper still parse defensively.

    Recorded live SpeechKit golden data verifies the ``result.final`` framing.
    The parser nevertheless tolerates a bare StreamingResponse envelope as
    defensive compatibility for variant or future input.

    Returns:
        None
    """
    body = _wire(
        [_finalEvent("bare text", startMs=0, endMs=1000)],
        wrapped=False,
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.FINAL
    assert [segment.text for segment in result.segments] == ["bare text"]


def testConcatenatedObjectsWithoutDelimiterParse() -> None:
    """Consecutive objects with NO inter-object delimiter parse (raw_decode walk).

    Returns:
        None
    """
    obj = json.dumps({"result": {"final": {"alternatives": [{"text": "a", "startTimeMs": 0, "endTimeMs": 1}]}}})
    body = (obj + obj).encode("utf-8")  # back-to-back, no whitespace
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.FINAL
    assert [segment.text for segment in result.segments] == ["a", "a"]


# ============================================================================
# Confidence field present but ignored (§7.3: do not build v1 around it)
# ============================================================================


def testConfidenceFieldIsIgnored() -> None:
    """A ``confidence`` field on an alternative does not affect parsing.

    §7.3: confidence exists but is documented as currently unused; do not build
    v1 behavior around it. It is present on both alternatives here and must not
    affect selection or output.

    Returns:
        None
    """
    body = json.dumps(
        {
            "result": {
                "final": {
                    "alternatives": [
                        {"text": "text", "startTimeMs": 0, "endTimeMs": 1, "confidence": 0.42},
                        {"text": "alt", "startTimeMs": 0, "endTimeMs": 1, "confidence": 0.99},
                    ]
                }
            }
        }
    ).encode("utf-8")
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].text == "text"


# ============================================================================
# Phase-4 Gate-1 review — never-raise-contract regression coverage
#
# _coerceInt's float and string-fallback branches both used to call
# ``int(float(...))`` which raises OverflowError (an ArithmeticError, NOT a
# ValueError) for non-finite inputs. The boundary ``except`` at line 119 only
# caught (UnicodeDecodeError, ValueError, TypeError, KeyError, IndexError), so
# an OverflowError from _coerceInt propagated out of parseRecognitionEvents — a
# direct violation of load-bearing contract #2 ("this module NEVER raises for
# expected/malformed input"). These tests reproduce all three reachability
# vectors and MUST FAIL before the fix.
# ============================================================================


@pytest.mark.parametrize("badStart", ["inf", "-inf", "1e400", "-1e400", "nan", "infinity"])
def testNonFiniteTimestampYieldsProtocolError(badStart: str) -> None:
    """A non-finite segment-timestamp string yields PROTOCOL_ERROR, never raise.

    Regression: before the fix, ``_coerceInt`` fell through to
    ``int(float(badStart))`` which raised ``OverflowError`` (an
    ``ArithmeticError``, NOT a ``ValueError``), escaping the never-raise
    boundary and propagating out of ``parseRecognitionEvents``.

    Covers all non-finite string spellings the ``str`` branch of ``_coerceInt``
    routes through ``float(...)``: positive/negative overflow (``"1e400"`` /
    ``"-1e400"``), the ``inf``/``-inf``/``infinity`` tokens, and ``"nan"``
    (``math.isfinite`` rejects all of them — the docstring names inf/nan).

    Args:
        badStart: A decimal string whose ``float()`` is non-finite.

    Returns:
        None
    """
    body = _wire([_finalEvent("text", startMs=badStart, endMs=1000)])
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


@pytest.mark.parametrize("token", ["Infinity", "-Infinity", "NaN"])
def testJsonNonFiniteTokenYieldsProtocolError(token: str) -> None:
    """A literal JSON non-finite numeric token in a timestamp yields PROTOCOL_ERROR.

    Regression: CPython's ``json`` scanner accepts ``Infinity`` / ``-Infinity`` /
    ``NaN`` by default, producing a Python non-finite ``float`` that hit the
    ``isinstance(value, float)`` branch of ``_coerceInt`` and raised
    ``OverflowError`` via ``int(value)``, escaping the never-raise boundary.
    The body is raw bytes because the upstream wire (not ``json.dumps``) is the
    producer of these tokens. Sibling to
    :func:`testNonFiniteTimestampYieldsProtocolError`, which covers the string
    spellings; this covers the JSON-numeric-token spellings.

    Args:
        token: A non-finite JSON numeric token the scanner accepts.

    Returns:
        None
    """
    body = (
        b'{"result":{"final":{"alternatives":[{"text":"x",'
        b'"startTimeMs":' + token.encode("ascii") + b',"endTimeMs":1}]}}}'
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


def testNonFiniteWordTimestampYieldsProtocolError() -> None:
    """A non-finite per-word timestamp yields PROTOCOL_ERROR, never raise.

    Regression: the OverflowError escape is also reachable at word level via
    ``_extractWords`` → ``_coerceInt`` (same ``int(float("inf"))`` path).

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent(
                "one two",
                startMs=0,
                endMs=2000,
                words=[_word("one", 0, "inf"), _word("two", 1000, 2000)],
            )
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


# ============================================================================
# Phase-4 Gate-1 review — ambiguity-#5 refinement-resolution coverage
#
# Pins the three refinement shapes the developer resolved but left unpinned:
# an orphan finalIndex (ignored), a refinement without normalizedText (ignored),
# and a refinement with normalizedText but NO finalIndex (strict -> KeyError ->
# PROTOCOL_ERROR). The first two are the lenient resolutions; the third is the
# stricter one. These lock all three in place against silent regressions.
# ============================================================================


def testOrphanRefinementIsIgnored() -> None:
    """A refinement whose finalIndex is out of range is ignored; raw text kept.

    Pins the lenient resolution: a refinement keyed to a finalIndex with no
    matching final (here 99, when only one final exists at index 0) is stored but
    never matched during the final-enumeration pass, so the raw final text stands.

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("only", startMs=0, endMs=1000),
            _refinementEvent(finalIndex=99, text="would-be-normalized"),
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.FINAL
    assert [segment.text for segment in result.segments] == ["only"]


def testRefinementWithoutNormalizedTextIsIgnored() -> None:
    """A finalRefinement with finalIndex but no normalizedText is ignored.

    Pins the lenient resolution: a refinement carrying only finalIndex (e.g. an
    unknown future refinement type) performs no text replacement, so the raw final
    text is kept. The payload is built by hand because ``_refinementEvent`` always
    sets normalizedText.

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("raw", startMs=0, endMs=1000),
            {"finalRefinement": {"finalIndex": 0}},  # no normalizedText
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.FINAL
    assert [segment.text for segment in result.segments] == ["raw"]


@pytest.mark.parametrize("speakerLabelingRequested", [False, True])
@pytest.mark.parametrize("invalidIndex", [0.5, -1, True, " 0"])
def testMalformedRefinementIndexWithoutNormalizedTextYieldsProtocolError(
    speakerLabelingRequested: bool, invalidIndex: object
) -> None:
    """A supplied malformed refinement index is rejected even without text content.

    Args:
        speakerLabelingRequested: Whether to exercise ordinary or speaker mode.
        invalidIndex: A malformed non-null refinement index.

    Returns:
        None
    """
    final = _finalEvent("raw", startMs=0, endMs=1000)
    if speakerLabelingRequested:
        final["channelTag"] = "speaker-1"
        final["audioCursors"] = {"finalIndex": 0}

    result = parseRecognitionEvents(
        _wire([final, {"finalRefinement": {"finalIndex": invalidIndex}}]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=speakerLabelingRequested,
    )

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR
    assert result.segments == ()


def testRefinementWithNormalizedTextButNoFinalIndexYieldsProtocolError() -> None:
    """A refinement with normalizedText but no finalIndex yields PROTOCOL_ERROR.

    Pins the stricter resolution for this ambiguity-#5 case: when normalizedText IS
    present the finalIndex is required (``refinement["finalIndex"]`` raises
    ``KeyError``, caught by the boundary), turning the whole stream into
    PROTOCOL_ERROR — stricter than the two lenient cases above. The payload is
    built by hand because ``_refinementEvent`` always sets finalIndex.

    Returns:
        None
    """
    body = _wire(
        [
            _finalEvent("raw", startMs=0, endMs=1000),
            {"finalRefinement": {"normalizedText": {"alternatives": [{"text": "norm"}]}}},
        ]
    )
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


@pytest.mark.parametrize("speakerLabelingRequested", [False, True])
def testRefinementWithNullFinalIndexYieldsProtocolErrorWithoutReplacingFinal(
    speakerLabelingRequested: bool,
) -> None:
    """A null refinement cursor is rejected rather than coercing to final index zero.

    A null ``finalRefinement.finalIndex`` is an incomplete refinement, unlike a
    missing proto3 timestamp. It must not enter either refinement map, so the
    parser rejects the malformed event atomically with ``PROTOCOL_ERROR`` rather
    than allowing its normalized text to overwrite a valid index-zero final.

    Args:
        speakerLabelingRequested: Whether to exercise the ordinary or composite
            speaker-refinement correlation path.

    Returns:
        None
    """
    final = _finalEvent("raw index zero", startMs=0, endMs=1000)
    if speakerLabelingRequested:
        final["channelTag"] = "speaker-1"
        final["audioCursors"] = {"finalIndex": 0}
    refinement = _refinementEvent(finalIndex=None, text="must not replace")
    if speakerLabelingRequested:
        refinement["channelTag"] = "speaker-1"

    result = parseRecognitionEvents(
        _wire([final, refinement]),
        maxResultBytes=_ROOMY_CAP,
        speakerLabelingRequested=speakerLabelingRequested,
    )

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR
    assert result.segments == ()


# ============================================================================
# Phase-4 Gate-1 review — wrong-typed ``alternatives`` promoted to PROTOCOL_ERROR
# ============================================================================


def testNonListAlternativesYieldsProtocolError() -> None:
    """A non-list ``alternatives`` field yields PROTOCOL_ERROR (consistency).

    A wrong-typed ``alternatives`` (here a JSON object) is a structural defect just
    like a non-string ``text`` or non-list ``words``; it is promoted to
    PROTOCOL_ERROR for consistency with those stricter fields rather than being
    silently treated as "no alternatives" (empty final -> filtered).

    Returns:
        None
    """
    body = b'{"result":{"final":{"alternatives":{"text":"x","startTimeMs":0,"endTimeMs":1}}}}'
    result = parseRecognitionEvents(body, maxResultBytes=_ROOMY_CAP)
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR
