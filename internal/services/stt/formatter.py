"""Pure transcript formatter for lib.stt.

Exposes one pure function (:func:`formatTranscript`) that turns a
:class:`~lib.stt.models.TranscriptionResult` into a timestamped plain-text
string.  The formatter is deliberately pure: it imports only the standard
library and :mod:`lib.stt.models`, holds no state, and must not raise for
any ``TranscriptionResult``.

Format: one line per non-empty segment. A segment with a non-empty
``attributionTag`` renders as ``[Speaker#<tag>] [start..end] text`` when the
result-level ``attributionType`` is SPEAKER. In CHANNEL mode, it renders as
``[Ch#<tag>] [start..end] text`` only when the result spans MORE than one
distinct non-empty tag; otherwise it renders as ``[start..end] text``. When
start and end are equal, the current formatter renders the single-timestamp
form ``[start] text`` instead.
Timestamps use millisecond precision when the sub-second component is non-zero.
Empty segments are skipped; a result with all empty segments yields ``""``. No
untrusted header, no XML escaping, no truncation, no ``[No speech detected]``
sentinel.
"""

from lib.stt.models import STTAttributionType, TranscriptionResult


def formatTranscript(result: TranscriptionResult) -> str:
    """Format a TranscriptionResult into a timestamped plain-text string.

    Builds one line per non-empty segment in the order given (the formatter
    does NOT re-sort; ordering is the caller's responsibility).  Each line
    is ``[Speaker#<tag>] [start..end] text`` when the result-level
    ``attributionType`` is SPEAKER and ``segment.attributionTag`` is non-empty.
    In CHANNEL mode, it is ``[Ch#<tag>] [start..end] text`` only when the result
    has MORE than one distinct non-empty attribution tag; otherwise it is
    ``[start..end] text``. When ``startMs == endMs``, the range is rendered as
    one timestamp instead. Timestamps use millisecond precision when the
    sub-second component is non-zero. Empty segments (after stripping) are
    skipped.

    The function is pure and must not raise for any ``TranscriptionResult``;
    it is segment-driven and ignores ``result.status``.

    Args:
        result: The provider-neutral transcription result. Each segment's
            ``text``, ``startMs``, ``endMs``, and ``attributionTag`` plus the
            result-level ``attributionType`` are consumed; ``status`` and
            ``errorCode`` are ignored by this function.

    Returns:
        str: The formatted transcript. Empty string when all segments are
            empty; otherwise newline-joined lines — ``[Speaker#<tag>]
            [start..end] text`` for speaker-attributed segments, ``[Ch#<tag>]
            [start..end] text`` for multi-channel results with a per-segment
            attribution tag, ``[start..end] text`` otherwise (or their
            single-timestamp forms when the segment start and end are equal).
    """
    lines: list[str] = []
    attributionsCount = len(set([segment.attributionTag for segment in result.segments if segment.attributionTag]))
    attributionPrefix = "Speaker" if result.attributionType == STTAttributionType.SPEAKER else "Ch"
    for segment in result.segments:
        normalizedText = segment.text.strip()
        if not normalizedText:
            continue
        beginTS = _formatTimestamp(segment.startMs)
        timestamp = beginTS
        if segment.startMs != segment.endMs:
            endTS = _formatTimestamp(segment.endMs)
            timestamp = beginTS + ".." + endTS

        attributionTag = segment.attributionTag
        attributionStr = ""
        if attributionTag and attributionsCount > 1:
            # If there is only one channel\speaker, then don't include the channel tag.
            attributionStr = f"[{attributionPrefix}#{attributionTag}] "

        lines.append(f"{attributionStr}[{timestamp}] {normalizedText}")
    return "\n".join(lines)


def _formatTimestamp(startMs: int) -> str:
    """Format a millisecond offset as ``[HH:MM:SS.mmm]`` with hours at least 2 digits.

    Args:
        startMs: The segment start time in milliseconds.

    Returns:
        str: The ``[HH:MM:SS.mmm]`` string (hours zero-padded to a minimum width
        of 2, so values ≥ 1 hour expand naturally, e.g. ``[01:00:00.001]``,
        ``[10:00:00.010]``). The ``.mmm`` suffix is omitted when
        ``milliseconds == 0``, yielding ``[HH:MM:SS]``.
    """
    totalSec = startMs // 1000
    hours = totalSec // 3600
    minutes = (totalSec % 3600) // 60
    seconds = totalSec % 60
    milliseconds = startMs % 1000
    millisecondsStr = f".{milliseconds:03d}" if milliseconds else ""

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{millisecondsStr}"
