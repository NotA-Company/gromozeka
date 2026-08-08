"""Pure transcript formatter for lib.stt.

Exposes one pure function (:func:`formatTranscript`) that turns a
:class:`~lib.stt.models.TranscriptionResult` into a timestamped plain-text
string.  The formatter is deliberately pure: it imports only the standard
library and :mod:`lib.stt.models`, holds no state, and must not raise for
any ``TranscriptionResult``.

Format: one line per non-empty segment, ``[HH:MM:SS.mmm] text`` (millisecond
precision when the sub-second component is non-zero).  Empty segments are
skipped; a result with all empty segments yields ``""``.  No untrusted header,
no XML escaping, no truncation, no ``[No speech detected]`` sentinel.
"""

from lib.stt.models import TranscriptionResult


def formatTranscript(result: TranscriptionResult) -> str:
    """Format a TranscriptionResult into a timestamped plain-text string.

    Builds one line per non-empty segment in the order given (the formatter
    does NOT re-sort; ordering is the caller's responsibility).  Each line
    is ``[HH:MM:SS.mmm] text`` with millisecond precision when the
    sub-second component is non-zero.  Empty segments (after stripping) are
    skipped.

    The function is pure and must not raise for any ``TranscriptionResult``;
    it is segment-driven and ignores ``result.status``.

    Args:
        result: The provider-neutral transcription result. Only
            ``result.segments`` is consumed; ``status``/``errorCode`` are
            ignored by this function.

    Returns:
        str: The formatted transcript.  Empty string when all segments are
        empty; otherwise newline-joined ``[HH:MM:SS.mmm] text`` lines.
    """
    lines: list[str] = []
    for segment in result.segments:
        normalizedText = segment.text.strip()
        if not normalizedText:
            continue
        timestamp = _formatTimestamp(segment.startMs)
        lines.append(f"[{timestamp}] {normalizedText}")
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
