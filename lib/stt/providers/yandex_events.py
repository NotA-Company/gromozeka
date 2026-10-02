"""getRecognition streaming-JSON event parser for the Yandex SpeechKit v3 provider.

This module is the isolated live-wire parser (readiness correction #2,
``docs/design/lib-stt-v1.md`` §3/§7.3): a PURE, sync function that takes the raw
``getRecognition`` response body (the verified streaming-JSON event stream the
provider fetches) and turns it into a provider-neutral
:class:`~lib.stt.models.TranscriptionResult`. It performs no HTTP, no async I/O,
and no PyAV — it receives ``bytes`` and returns a ``TranscriptionResult``. Keeping
the live-wire parsing factored out here lets the stable provider class
(``yandex_speechkit.py``) stay focused on the wire lifecycle, and lets the parser
be unit-tested in isolation with golden fixtures (§9).

VERIFIED wire format (load-bearing contract #4, §7.3 / §10(a)): recorded live
SpeechKit responses in the committed aurumentation golden data verify the
``getRecognition`` streaming-JSON framing and its top-level ``result`` wrapper.
The parser centralises that wrapper in :func:`_resolveEnvelope`; accepting a bare
``StreamingResponse`` envelope remains defensive compatibility for variant or
future input, not a release gate. Golden tests assert the recorded framing and
event semantics.

Authoritative references:
- §7.3 (event parsing) and §8.1 (result-body cap = 5 MiB, owned here) of
  ``docs/design/lib-stt-v1.md``.
- v3 message proto ``yandex/cloud/ai/stt/v3/stt.proto``: ``StreamingResponse``
  carries the oneof ``Event`` with ``final`` (an ``AlternativeUpdate``) and
  ``final_refinement`` (a ``FinalRefinement`` whose ``normalized_text`` is an
  ``AlternativeUpdate``); ``Alternative`` carries ``text`` / ``start_time_ms`` /
  ``end_time_ms`` / ``words``; ``Word`` carries ``text`` + ms range.

Caps ownership (load-bearing contract #3, §8.1): the result-body cap
(``maxResultBytes``) is owned and enforced HERE, received as a parameter — this
module never reads ``[stt]`` config (the dependency firewall, §1).

Raise/return contract (load-bearing contract #2, §4): this module NEVER raises
for expected/malformed input — the only runtime raise-point inside ``lib/stt`` is
``audio.extractAudio()``. Unparseable / over-cap / malformed responses return
``TranscriptionResult(status=ERROR, errorCode=PROTOCOL_ERROR)``. §7.3 does not
contradict this (it does not specify that the parser raises), so this follows the
general §4 contract.
"""

import json
import math
import re
from typing import Dict, FrozenSet, List, Optional, Tuple, cast

from ..models import (
    STTAttributionType,
    STTErrorCode,
    STTResultStatus,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
)

#: Default result-body cap in bytes (5 MiB), per §8.1. Owned and enforced by this
#: module. The actual runtime value is injected by the provider/manager from
#: ``[stt].max-result-bytes`` config; this constant exists for documentation and
#: for tests. The cap is a parameter to :func:`parseRecognitionEvents`, not read
#: from config here.
DEFAULT_MAX_RESULT_BYTES: int = 5_242_880

#: JSON inter-object whitespace characters permitted between consecutive event
#: objects (per §7.3: "skipping only whitespace between objects").
_WHITESPACE: FrozenSet[str] = frozenset(" \t\n\r")

#: Canonical non-negative protobuf-JSON integer spelling accepted for cursor
#: identities. Unlike timestamps, identity keys must never be truncated or
#: normalized from alternative spellings.
_PROTOBUF_NON_NEGATIVE_INTEGER: re.Pattern[str] = re.compile(r"0|[1-9][0-9]*")


def parseRecognitionEvents(
    responseBytes: bytes,
    maxResultBytes: int,
    *,
    speakerLabelingRequested: bool = False,
) -> TranscriptionResult:
    """Parse a Yandex v3 ``getRecognition`` event stream into a TranscriptionResult.

    Reads the verified streaming-JSON event body, enforces the result-body cap,
    decodes UTF-8 strictly, parses consecutive top-level JSON event objects
    (allowing only whitespace between them and rejecting any other garbage), and
    folds the ``final`` + ``finalRefinement`` events into a provider-neutral
    result:

    - the **first alternative** of each ``final`` is taken (alternatives are
      competing hypotheses, not separate segments);
    - ``startTimeMs``/``endTimeMs`` (segment and per-word) are accepted as
      integers or decimal strings (protobuf JSON may encode ``int64`` as strings);
    - a matching ``finalRefinement.finalIndex`` **replaces** the raw final text
      with the normalized text (and normalized words when the refinement carries
      them), rather than emitting both — so no duplicate text is produced;
    - every canonical envelope-level ``channelTag`` becomes a stringified
      ``attributionTag`` (or None for missing, null, or empty); deprecated
      ``final.channelTag`` is never read;
    - the result-level ``attributionType`` is CHANNEL by default and SPEAKER
      when ``speakerLabelingRequested`` is true;
    - non-final events (``partial``, ``status_code``, ``eou_update``, …) are
      ignored;
    - final segments are **sorted by start time** before being returned;
    - when no non-empty final segment remains, the result is ``NO_SPEECH``.

    The function never raises for expected/malformed input. A body exceeding
    ``maxResultBytes``, invalid UTF-8, malformed JSON, trailing garbage, or a
    malformed event shape (bad timestamp, wrong type) yields
    ``TranscriptionResult(status=ERROR, errorCode=PROTOCOL_ERROR)``. Each
    ``getRecognition`` stream is atomic (§7.4): a single malformed event poisons
    the whole result rather than committing partial segments.

    Args:
        responseBytes: The raw ``getRecognition`` response body (the verified
            streaming-JSON event stream). Treated as opaque bytes; the cap is
            checked on the byte length BEFORE any decoding/parsing.
        maxResultBytes: The inclusive result-body byte cap (§8.1). A validated
            positive config value received as a parameter (the dependency
            firewall — this module never reads ``[stt]`` config).
        speakerLabelingRequested: Whether the caller explicitly requested
            Yandex speaker labeling for this recognition. Only this flag, not
            audio channel count or tag content, changes tag semantics.

    Returns:
        TranscriptionResult: ``FINAL`` with the recognised segments (sorted by
        start time) when one or more non-empty final segments were recognised;
        ``NO_SPEECH`` when recognition completed with no non-empty final segment
        (including an empty/whitespace-only event stream); or ``ERROR`` with
        ``errorCode=PROTOCOL_ERROR`` for an over-cap or unparseable response.
    """
    # Result-body cap (load-bearing contract #3): enforced on byte length before
    # any decoding or parsing, per §7.3 ("reads streaming bytes up to
    # max-result-bytes") and §8.1 (this module owns the result-byte cap).
    if len(responseBytes) > maxResultBytes:
        return _protocolError(speakerLabelingRequested=speakerLabelingRequested)

    try:
        text = responseBytes.decode("utf-8")  # strict UTF-8
        # print(text)
        events = _iterJsonObjects(text)
        return _buildResult(events, speakerLabelingRequested=speakerLabelingRequested)
    except (UnicodeDecodeError, ValueError, TypeError, KeyError, IndexError, ArithmeticError):
        # Malformed input of any kind (invalid UTF-8, broken JSON, trailing
        # garbage, a bad timestamp value, a wrong-typed field, or a numeric
        # coercion that overflows float range) is an expected failure →
        # PROTOCOL_ERROR, never raised (load-bearing contract #2). ``ArithmeticError``
        # is belt-and-braces: ``_coerceInt`` now converts non-finite values to
        # ``ValueError`` up front, but any other numeric-coercion ``ArithmeticError``
        # (e.g. ``OverflowError``) is caught here too rather than escaping.
        return _protocolError(speakerLabelingRequested=speakerLabelingRequested)


def _iterJsonObjects(text: str) -> List[object]:
    """Parse consecutive top-level JSON event objects from a stream string.

    Implements the §7.3 streaming-JSON framing parser: walks ``text``, skipping only
    JSON whitespace between objects, and parses each object with
    :meth:`json.JSONDecoder.raw_decode`. Only objects (``{...}``) are accepted at
    the top level — a bare array, atom, or any other character between/after
    objects is treated as garbage.

    Args:
        text: The decoded event stream (UTF-8).

    Returns:
        List[object]: The parsed top-level event objects, in stream order. Each
        element is a JSON object (narrowed to ``dict`` by :func:`_resolveEnvelope`
        during event processing).

    Raises:
        ValueError: On a JSON decode failure or any non-whitespace garbage that
            is not the start of an object.
    """
    decoder = json.JSONDecoder()
    objects: List[object] = []
    idx = 0
    length = len(text)
    while idx < length:
        # Skip only whitespace between/around objects (§7.3).
        while idx < length and text[idx] in _WHITESPACE:
            idx += 1
        if idx >= length:
            break
        # Events are objects; a non-'{' byte here is trailing/inter-object garbage.
        if text[idx] != "{":
            raise ValueError(f"expected a JSON object at offset {idx}, got {text[idx]!r}")
        parsed, end = decoder.raw_decode(text, idx)
        objects.append(parsed)
        idx = end
    return objects


def _buildResult(events: List[object], *, speakerLabelingRequested: bool) -> TranscriptionResult:
    """Fold parsed event objects into a TranscriptionResult per §7.3 semantics.

    In ordinary mode, collects ``final`` events in stream order (their position
    IS their ``finalIndex``) and ``finalRefinement`` events keyed by bare
    ``finalIndex``. In speaker mode, a final and refinement that both carry a
    canonical envelope tag are instead correlated by ``(canonicalTag,
    finalIndex)``. This prevents independently numbered speaker streams from
    overwriting each other's refinements. Missing cursor metadata falls back to
    the existing bare-index association while retaining canonical wire
    attribution. The matched refinement replaces raw text — and words when it
    carries them — while selected attribution survives unchanged. Empty-text
    segments are dropped and survivors are sorted by start time. Returns
    ``NO_SPEECH`` when nothing non-empty remains.

    Args:
        events: The parsed top-level event objects (from :func:`_iterJsonObjects`).
        speakerLabelingRequested: Whether canonical envelope tags represent
            speaker labels rather than ordinary audio-channel metadata.

    Returns:
        TranscriptionResult: The folded, sorted result. ``NO_SPEECH`` when no
        non-empty final segment survived.

    Raises:
        ValueError/TypeError/KeyError/IndexError: On any malformed event shape
            (non-object event, wrong-typed field, uncoercible timestamp); caught
            by :func:`parseRecognitionEvents` and turned into ``PROTOCOL_ERROR``.
    """
    rawFinals: List[Tuple[_RawFinal, Optional[Tuple[str, int]]]] = []
    refinements: Dict[int, Dict[str, object]] = {}
    speakerRefinements: Dict[Tuple[str, int], Dict[str, object]] = {}

    for event in events:
        envelope = _resolveEnvelope(event)
        canonicalTag = _normalizeTag(envelope.get("channelTag")) if "channelTag" in envelope else None
        if "final" in envelope:
            finalUpdate = envelope["final"]
            finalIndex = _getEnvelopeFinalIndex(envelope)
            alternative = _firstAlternative(finalUpdate)
            speakerRefinementKey: Optional[Tuple[str, int]] = None
            if speakerLabelingRequested:
                if canonicalTag is not None and finalIndex is not None:
                    speakerRefinementKey = (canonicalTag, finalIndex)
            rawFinals.append(
                (
                    _extractFinal(
                        alternative,
                        attributionTag=canonicalTag,
                    ),
                    speakerRefinementKey,
                )
            )
        if "finalRefinement" in envelope:
            refinement = envelope["finalRefinement"]
            if isinstance(refinement, dict):
                finalIndex: Optional[int] = None
                if "finalIndex" in refinement:
                    if refinement["finalIndex"] is None:
                        raise ValueError("finalRefinement finalIndex cannot be null")
                    finalIndex = _coerceFinalIndex(refinement["finalIndex"])
                normalizedUpdate = refinement.get("normalizedText")
                # A refinement without normalizedText (e.g. an unknown future
                # refinement type) carries no text replacement → ignore it and
                # keep the raw final text. When normalizedText IS present the
                # finalIndex is required; unlike an absent proto3 timestamp, a
                # null refinement index is malformed and must never coerce to 0.
                if isinstance(normalizedUpdate, dict):
                    if finalIndex is None:
                        raise ValueError("finalRefinement finalIndex is required")
                    normalizedAlt = _firstAlternative(normalizedUpdate)
                    if normalizedAlt:
                        if speakerLabelingRequested and canonicalTag is not None:
                            speakerRefinements[(canonicalTag, finalIndex)] = normalizedAlt
                        else:
                            # Preserve the legacy bare-index fallback only for
                            # untagged refinements. Tagged speaker refinements
                            # must not cross-apply to untagged/cursorless finals
                            # sharing their provider-local index.
                            refinements[finalIndex] = normalizedAlt

    segments: List[TranscriptionSegment] = []
    for index, (raw, speakerRefinementKey) in enumerate(rawFinals):
        normalizedAlt = (
            speakerRefinements.get(speakerRefinementKey) if speakerRefinementKey is not None else refinements.get(index)
        )
        text, startMs, endMs, words, attributionTag = _applyRefinement(raw, normalizedAlt)
        if text.strip():
            segments.append(
                TranscriptionSegment(
                    text=text,
                    startMs=startMs,
                    endMs=endMs,
                    words=words,
                    attributionTag=attributionTag,
                )
            )

    if not segments:
        return _noSpeech(speakerLabelingRequested=speakerLabelingRequested)

    segments.sort(key=lambda segment: segment.startMs)
    attributionType = STTAttributionType.SPEAKER if speakerLabelingRequested else STTAttributionType.CHANNEL
    return TranscriptionResult(status=STTResultStatus.FINAL, segments=tuple(segments), attributionType=attributionType)


def _getEnvelopeFinalIndex(envelope: Dict[str, object]) -> Optional[int]:
    """Get an envelope finalIndex when the event supplies a usable cursor.

    Speaker-mode correlation is only more precise than the legacy bare stream
    position when the canonical speaker tag and this cursor are both present.
    Missing or null cursor metadata therefore returns None so callers can
    preserve the old bare-index fallback.

    Args:
        envelope: The resolved StreamingResponse envelope for a final event.

    Returns:
        Optional[int]: The cursor final index, or None when audioCursors or its
        finalIndex field is absent or null.

    Raises:
        ValueError: If an explicitly supplied finalIndex cannot be coerced to an
            integer; the parser boundary turns this into PROTOCOL_ERROR.
    """
    if "audioCursors" not in envelope or envelope["audioCursors"] is None:
        return None
    audioCursors = envelope["audioCursors"]
    if not isinstance(audioCursors, dict):
        raise ValueError(f"audioCursors is not a JSON object: {type(audioCursors).__name__}")
    if "finalIndex" not in audioCursors:
        return None
    if audioCursors["finalIndex"] is None:
        return None
    return _coerceFinalIndex(audioCursors["finalIndex"])


def _coerceFinalIndex(value: object) -> int:
    """Validate a final/refinement map key as a protobuf-JSON non-negative integer.

    Cursor identities are stricter than timestamps: only JSON integer values and
    canonical decimal protobuf-JSON integer strings are accepted. This prevents
    fractional, negative, boolean, whitespace-padded, and otherwise normalized
    representations from aliasing another final's map key.

    Args:
        value: A non-null ``audioCursors.finalIndex`` or
            ``finalRefinement.finalIndex`` value.

    Returns:
        int: The exact non-negative final index.

    Raises:
        ValueError: If ``value`` is not an exact non-negative protobuf-JSON
            integer representation.
    """
    if isinstance(value, bool):
        raise ValueError("finalIndex must not be bool")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("finalIndex must be non-negative")
        return value
    if isinstance(value, str) and _PROTOBUF_NON_NEGATIVE_INTEGER.fullmatch(value):
        return int(value)
    raise ValueError(f"finalIndex is not a canonical non-negative integer: {value!r}")


def _resolveEnvelope(event: object) -> Dict[str, object]:
    """Resolve a parsed event object to its StreamingResponse envelope.

    Verified framing (load-bearing contract #4, §7.3): committed aurumentation
    golden data records live SpeechKit responses with each ``StreamingResponse``
    wrapped in a top-level ``result`` key (``result.final`` /
    ``result.finalRefinement``). The raw proto has no such field, so the wrapper
    is gateway framing. This helper also accepts the bare form (``{...}``) as
    defensive compatibility for variant or future input; it is not a release
    blocker. The framing choice remains isolated here for maintainability.

    Args:
        event: One parsed top-level object from :func:`_iterJsonObjects`.

    Returns:
        Dict[str, object]: The envelope to read ``final``, ``finalRefinement``,
        and canonical ``channelTag`` from (the wrapped value when a ``result``
        key holding a dict is present, otherwise ``event`` itself).

    Raises:
        ValueError: If ``event`` is not a JSON object.
    """
    if not isinstance(event, dict):
        raise ValueError(f"event is not a JSON object: {type(event).__name__}")
    resultField = event.get("result")
    if isinstance(resultField, dict):
        return cast(Dict[str, object], resultField)
    return cast(Dict[str, object], event)


def _firstAlternative(update: object) -> Dict[str, object]:
    """Select the first alternative of an AlternativeUpdate (§7.3).

    Alternatives are competing hypotheses for the same time frame, not separate
    segments, so only ``alternatives[0]`` is consumed. A missing or empty
    ``alternatives`` list yields an empty dict (an empty-text final that is later
    filtered) rather than an error — a final event with no alternatives is odd
    but not stream-garbage. A non-list ``alternatives`` (e.g. a JSON object) is a
    structural defect on par with a non-string ``text`` or non-list ``words`` and
    is rejected with ``ValueError`` (→ PROTOCOL_ERROR) for consistency with those
    stricter fields, rather than being silently coerced to "no alternatives".

    Args:
        update: An ``AlternativeUpdate`` value (``final`` / ``normalizedText``).

    Returns:
        Dict[str, object]: The first alternative, or an empty dict when there are
        no alternatives.

    Raises:
        ValueError: If ``update`` is not an object, ``alternatives`` is present but
            not a list, or an alternative is present but is not a JSON object.
    """
    if not isinstance(update, dict):
        raise ValueError(f"alternative update is not a JSON object: {type(update).__name__}")
    alternatives = update.get("alternatives")
    if alternatives is None:
        return {}
    if not isinstance(alternatives, list):
        raise ValueError(f"alternatives is not a list: {type(alternatives).__name__}")
    if not alternatives:
        return {}
    first = alternatives[0]
    if not isinstance(first, dict):
        raise ValueError(f"first alternative is not a JSON object: {type(first).__name__}")
    return cast(Dict[str, object], first)


def _extractFinal(
    alternative: Dict[str, object],
    *,
    attributionTag: Optional[str] = None,
) -> "_RawFinal":
    """Extract a raw final (text + ms range + words) from one Alternative.

    Timestamps are coerced via :func:`_coerceInt` (integers or decimal strings);
    missing timestamps default to 0 (proto3 int64 default). An absent/empty
    ``words`` list yields no words.

    Args:
        alternative: The chosen first ``Alternative`` of a ``final`` event.
        attributionTag: Canonical unified attribution tag.

    Returns:
        _RawFinal: The extracted raw final record, including its attribution.

    Raises:
        ValueError: If ``text`` is present but not a string, or a timestamp/word
            value cannot be coerced.
    """
    text = alternative.get("text", "")
    if not isinstance(text, str):
        raise ValueError(f"final text is not a string: {type(text).__name__}")
    startMs = _coerceInt(alternative.get("startTimeMs", 0))
    endMs = _coerceInt(alternative.get("endTimeMs", 0))
    words = _extractWords(alternative.get("words"))
    return _RawFinal(
        text=text,
        startMs=startMs,
        endMs=endMs,
        words=tuple(words),
        attributionTag=attributionTag,
    )


def _extractWords(wordsValue: object) -> List[TranscriptionWord]:
    """Extract Word records from an Alternative's ``words`` list.

    Each word's ``text`` defaults to the empty string; ``startTimeMs``/``endTimeMs``
    are coerced via :func:`_coerceInt` and default to 0 when absent (proto3).

    Args:
        wordsValue: The ``words`` value of an Alternative (a list, or None/absent).

    Returns:
        List[TranscriptionWord]: The extracted words, in order. Empty when
        ``wordsValue`` is None.

    Raises:
        ValueError: If ``wordsValue`` is not None and not a list, or a word/word
            field has an unexpected type.
    """
    if wordsValue is None:
        return []
    if not isinstance(wordsValue, list):
        raise ValueError(f"words is not a list: {type(wordsValue).__name__}")
    words: List[TranscriptionWord] = []
    for rawWord in wordsValue:
        if not isinstance(rawWord, dict):
            raise ValueError(f"word is not a JSON object: {type(rawWord).__name__}")
        wordText = rawWord.get("text", "")
        if not isinstance(wordText, str):
            raise ValueError(f"word text is not a string: {type(wordText).__name__}")
        wordStart = _coerceInt(rawWord.get("startTimeMs", 0))
        wordEnd = _coerceInt(rawWord.get("endTimeMs", 0))
        words.append(TranscriptionWord(text=wordText, startMs=wordStart, endMs=wordEnd))
    return words


def _applyRefinement(
    raw: "_RawFinal", normalizedAlt: Optional[Dict[str, object]]
) -> Tuple[str, int, int, Tuple[TranscriptionWord, ...], Optional[str]]:
    """Apply a finalRefinement to a raw final, per §7.3.

    §7.3 says to "replace the raw final text with normalized text rather than
    emitting both". This helper replaces the TEXT with the refinement's
    normalized text and, when the refinement carries its own words, replaces the
    WORDS too (to keep word alignment with the normalized text). The segment ms
    range is kept from the raw final — the normalized text describes the same
    utterance/time frame. When no refinement matches, the raw final is returned
    unchanged.

    The interpretation choice (also replacing words, preserving the raw time
    range) is flagged here: §7.3 explicitly names only "text", so the
    text replacement is the load-bearing part; the word replacement is the most
    coherent reading (keeps words aligned with the now-normalized text) and
    degrades to keeping the raw words when the refinement carries none.

    Args:
        raw: The raw final record (text + ms range + words + attribution).
        normalizedAlt: The refinement's first normalized Alternative, or None
            when no refinement matched this final.

    Returns:
        Tuple[str, int, int, Tuple[TranscriptionWord, ...], Optional[str]]:
        The ``(text, startMs, endMs, words, attributionTag)`` to build the
        segment from. Attribution is preserved through refinement.
    """
    if normalizedAlt is None:
        return raw.text, raw.startMs, raw.endMs, raw.words, raw.attributionTag
    normalizedText = normalizedAlt.get("text", "")
    if not isinstance(normalizedText, str):
        # A refinement present but with a non-string text is malformed for our
        # purposes; fall back to the raw text rather than poisoning the stream.
        # Deliberate asymmetry with _extractWords (which REJECTS a non-list
        # words): a raw final is load-bearing, so a malformed field there fails
        # the stream, whereas a refinement is an enhancement on top of an
        # already-valid final, so a malformed refinement degrades to the raw
        # final instead.
        normalizedText = raw.text
    normalizedWords = _extractWords(normalizedAlt.get("words"))
    words: Tuple[TranscriptionWord, ...] = tuple(normalizedWords) if normalizedWords else raw.words
    return normalizedText, raw.startMs, raw.endMs, words, raw.attributionTag


def _normalizeTag(value: object) -> Optional[str]:
    """Normalize an optional canonical Yandex envelope tag.

    Args:
        value: The raw JSON field value from the canonical envelope location.

    Returns:
        Optional[str]: None for a missing, null, or empty tag; otherwise the
        string form of the JSON value.
    """
    if value is None or value == "":
        return None
    return str(value)


def _coerceInt(value: object) -> int:
    """Coerce a protobuf-JSON int64 value (decimal string or int) to an int.

    §7.3: accept ``startTimeMs``/``endTimeMs`` as decimal strings or integers,
    because protobuf JSON may encode ``int64`` as strings. This helper accepts a
    Python int, an integral float, or a base-10 numeric string (optionally with a
    fractional part). ``None`` is treated as 0 (proto3 int64 default for an
    absent field). Booleans are rejected explicitly (``bool`` subclasses ``int``
    in Python, so ``True`` must not become ``1``).

    Non-finite values are rejected: a non-finite float (``inf`` / ``nan``) or a
    numeric string that overflows to infinity (``"inf"`` / ``"1e400"``) raises
    ``ValueError`` rather than ``OverflowError``, so the never-raise boundary in
    :func:`parseRecognitionEvents` catches it (load-bearing contract #2).

    Truncation note: int64 ms values are expected to be integral, but a
    non-integral float or decimal string (e.g. ``1.9`` or ``"1.9"``) is accepted
    and **truncated toward zero** via ``int(...)`` (so ``_coerceInt(1.9) == 1``,
    ``_coerceInt(-1.9) == -1``). This is intentional passthrough of CPython's
    ``int(float)`` semantics rather than rounding; protobuf int64 ms values
    should never legitimately be fractional, so the truncation is a defined
    fallback, not silent data loss.

    Underscore note: because parsing goes through CPython's ``int()``, an
    underscored numeric string such as ``"1_000"`` is accepted as ``1000``
    (Python digit-separator syntax). Protobuf-JSON int64 strings never contain
    underscores, so this is a documented passthrough of ``int()`` semantics
    rather than a wire feature.

    Args:
        value: The raw timestamp value from a parsed event.

    Returns:
        int: The coerced millisecond value.

    Raises:
        ValueError: If ``value`` is a bool, a non-finite float/string, or any
            type that cannot be coerced.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError(f"expected int or decimal string, got bool: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"timestamp must be finite, got {value!r}")
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return int(stripped)
        except ValueError:
            asFloat = float(stripped)  # ValueError for non-numeric -> caught upstream
            if not math.isfinite(asFloat):
                raise ValueError(f"timestamp must be finite, got {value!r}")
            return int(asFloat)
    raise ValueError(f"expected int or decimal string, got {type(value).__name__}")


def _protocolError(*, speakerLabelingRequested: bool = False) -> TranscriptionResult:
    """Build the PROTOCOL_ERROR result for an over-cap or unparseable response.

    Returns:
        TranscriptionResult: ``status=ERROR`` with
        ``errorCode=STTErrorCode.PROTOCOL_ERROR`` and no segments.
    """
    attributionType = STTAttributionType.SPEAKER if speakerLabelingRequested else STTAttributionType.CHANNEL
    return TranscriptionResult(
        status=STTResultStatus.ERROR,
        segments=(),
        errorCode=STTErrorCode.PROTOCOL_ERROR,
        attributionType=attributionType,
    )


def _noSpeech(*, speakerLabelingRequested: bool) -> TranscriptionResult:
    """Build the NO_SPEECH result for a completed recognition with no final text.

    Returns:
        TranscriptionResult: ``status=NO_SPEECH`` with no segments.
    """
    attributionType = STTAttributionType.SPEAKER if speakerLabelingRequested else STTAttributionType.CHANNEL
    return TranscriptionResult(status=STTResultStatus.NO_SPEECH, segments=(), attributionType=attributionType)


class _RawFinal:
    """Internal mutable-ish scratch record for a collected final event.

    ``__slots__`` (no dataclass) keeps this lightweight; it is only ever held
    within :func:`_buildResult` and never escapes the module.

    Attributes:
        text: The raw (pre-refinement) final text.
        startMs: The final start time in milliseconds.
        endMs: The final end time in milliseconds.
        words: The raw final words (pre-refinement).
        attributionTag: Canonical unified attribution tag.
    """

    __slots__ = ("text", "startMs", "endMs", "words", "attributionTag")

    def __init__(
        self,
        text: str,
        startMs: int,
        endMs: int,
        words: Tuple[TranscriptionWord, ...],
        attributionTag: Optional[str] = None,
    ) -> None:
        """Initialize the raw final scratch record.

        Args:
            text: The raw (pre-refinement) final text.
            startMs: The final start time in milliseconds.
            endMs: The final end time in milliseconds.
            words: The raw final words (pre-refinement).
            attributionTag: Canonical unified attribution tag.

        Returns:
            None
        """
        self.text = text
        self.startMs = startMs
        self.endMs = endMs
        self.words = words
        self.attributionTag = attributionTag
