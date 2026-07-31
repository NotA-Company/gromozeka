"""Provider-neutral data models for the lib.stt Speech-to-Text library.

This module is the pure-data foundation of ``lib/stt``: it defines the enums,
immutable records, and the typed media-loader boundary used across the whole
STT pipeline. It deliberately imports only the standard library (``enum``,
``dataclasses``, ``typing``) and MUST NOT import ``internal.bot``,
``internal.database``, any singleton service, or ``lib.stt.exceptions`` (the
exception module imports this one, not the reverse — see the dependency
firewall in ``docs/plans/lib-stt-v1.md`` §1).

Key components:
- STTResultStatus / STTErrorCode: outcome category and stable failure categories.
- STTAudioContainerType: the three inline audio containers a provider accepts
  (wire-fixed labels matching the Yandex SpeechKit v3 proto enum).
- TranscriptionWord / TranscriptionSegment / TranscriptionResult: the
  provider-neutral transcript record types.
- AudioFormatSpec: one accepted container format, the negotiation surface
  consumed by ``audio.py``.
- ExtractedAudio: format-aware audio handed to a provider after negotiation.
- STTLoaderResult + STTMediaLoader: the typed async loader boundary passed in
  by ``STTService`` (dependency-firewall seam #2).

See ``docs/plans/lib-stt-v1.md`` §4 for the authoritative prose on every type.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Awaitable, Callable, Optional, Tuple, TypeAlias


class STTResultStatus(StrEnum):
    """Outcome category of a transcription attempt."""

    FINAL = "final"
    """One or more non-empty final segments were recognized."""

    NO_SPEECH = "no-speech"
    """Valid recognition completed with no non-empty final segments."""

    ERROR = "error"
    """An expected failure occurred; see the accompanying STTErrorCode."""


class STTErrorCode(StrEnum):
    """Stable, provider-neutral failure categories.

    Not every code is produced inside lib/stt; see the raise/return contract
    in ``docs/plans/lib-stt-v1.md`` §4 for which codes are raised (audio.py),
    returned by the Yandex provider, or produced only by STTService/loader.
    """

    ADMISSION_TIMEOUT = "admission-timeout"
    """Admission wait elapsed before a worker was acquired.

    Produced by STTService; never raised inside lib/stt.
    """

    SOURCE_TOO_LARGE = "source-too-large"
    """Downloaded source byte length exceeded the source-bytes cap on recheck.

    Raised by audio.py.
    """

    SOURCE_SIZE_UNKNOWN = "source-size-unknown"
    """Source size could not be determined before download.

    Produced by STTService/loader; never raised inside lib/stt.
    """

    NO_AUDIO = "no-audio"
    """Source contained no decodable audio stream. Raised by audio.py."""

    AUDIO_TOO_LARGE = "audio-too-large"
    """Decoded in-memory PCM buffer or inline payload exceeded its cap. Raised by audio.py."""

    DURATION_EXCEEDED = "duration-exceeded"
    """Probed/decoded duration exceeded the cap on the pass-through path. Raised by audio.py."""

    DOWNLOAD_ERROR = "download-error"
    """Media download failed.

    Produced by STTService/loader; never raised inside lib/stt.
    """

    PROVIDER_ERROR = "provider-error"
    """Provider operation error, exhausted auth/429/5xx/timeout, or a decoder/muxer failure.

    Returned by the Yandex provider and raised by audio.py via
    AudioDecodeError/EncoderError.
    """

    PROTOCOL_ERROR = "protocol-error"
    """Malformed provider response, trailing garbage, or streamed result body over the result-byte cap.

    Returned by the Yandex provider.
    """


class STTAudioContainerType(StrEnum):
    """Audio containers a provider accepts inline.

    Mirrors the Yandex SpeechKit v3 ``ContainerAudio.ContainerAudioType`` proto
    enum, which has exactly three members: WAV, OGG_OPUS, MP3 (there is no
    AIFF/AC3/FLAC in the enum). ``RawAudio`` / ``LINEAR16_PCM`` is intentionally
    not modelled here: v1 always submits a container, not headerless raw PCM.

    Unlike the two enums above, the string values here are the exact
    protobuf-JSON labels the Yandex provider writes into
    ``container_audio.container_audio_type``; they are fixed by the wire
    contract, not freely chosen by the implementer.
    """

    WAV = "WAV"
    """WAV container (PCM with a RIFF header)."""

    OGG_OPUS = "OGG_OPUS"
    """Ogg container with an Opus codec (Telegram VOICE native shape)."""

    MP3 = "MP3"
    """MPEG-1/2 Audio Layer III container (common AUDIO shape)."""


@dataclass(frozen=True, slots=True)
class TranscriptionWord:
    """A single recognized word with its millisecond time range.

    Attributes:
        text: The recognized word text.
        startMs: Word start time in milliseconds.
        endMs: Word end time in milliseconds.
    """

    text: str
    startMs: int
    endMs: int


@dataclass(frozen=True, slots=True)
class TranscriptionSegment:
    """A final recognized utterance.

    Attributes:
        text: The (normalized) segment text.
        startMs: Segment start time in milliseconds.
        endMs: Segment end time in milliseconds.
        words: Immutable tuple of TranscriptionWord, preserved in memory for
            future use even though only formatted text is persisted.
    """

    text: str
    startMs: int
    endMs: int
    words: Tuple[TranscriptionWord, ...]


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Provider-neutral result of one transcription attempt.

    Attributes:
        status: The outcome category.
        segments: Immutable tuple of TranscriptionSegment; empty unless FINAL.
        errorCode: Present iff status == ERROR; identifies the failure category.
    """

    status: STTResultStatus
    segments: Tuple[TranscriptionSegment, ...]
    errorCode: Optional[STTErrorCode] = None


@dataclass(frozen=True, slots=True)
class AudioFormatSpec:
    """One container format a provider accepts inline.

    Describes the negotiation surface used by ``audio.py`` to decide pass-through
    vs. transcode. Does NOT describe recognition quality — quality-by-format is
    UNVERIFIED (see ``docs/plans/lib-stt-v1.md`` §10(b)); the proven win is
    payload size/traffic.

    Attributes:
        container: The accepted container.
        minChannels: Minimum accepted channel count (inclusive).
        maxChannels: Maximum accepted channel count (inclusive). SpeechKit
            accepts multi-channel async audio, but the exact ceiling is
            unpublished; set a generous value here and let the decoded-buffer
            cap (``docs/plans/lib-stt-v1.md`` §5) bound the actual multi-channel
            cost.
        minSampleRate: Minimum accepted sample rate in Hz (inclusive).
        maxSampleRate: Maximum accepted sample rate in Hz (inclusive).
    """

    container: STTAudioContainerType
    minChannels: int
    maxChannels: int
    minSampleRate: int
    maxSampleRate: int


@dataclass(frozen=True, slots=True)
class ExtractedAudio:
    """Format-aware audio handed to a provider after negotiation.

    The container is whatever the negotiation decided — the source container on
    a pass-through path, or the transcode target (OGG_OPUS for Yandex) on a
    transcode path. ``channels`` is ALWAYS the source channel count; it is never
    downmixed (hard rule, ``docs/plans/lib-stt-v1.md`` §5).

    Attributes:
        container: The container of ``data`` (WAV / OGG_OPUS / MP3).
        channels: Channel count preserved from the source (no downmix).
        sampleRate: Sample rate of ``data`` in Hz.
        data: The audio bytes the provider receives (source bytes on
            pass-through, PyAV-re-encoded bytes on transcode). Base64 encoding
            happens at the provider, not here.
        durationMs: Measured duration in milliseconds, derived from the actual
            sample count (pass-through probe / transcode encode), not container
            metadata alone.
    """

    container: STTAudioContainerType
    channels: int
    sampleRate: int
    data: bytes
    durationMs: int


@dataclass(frozen=True, slots=True)
class STTLoaderResult:
    """Result of the service-supplied bounded media loader.

    Attributes:
        data: The downloaded source bytes.
        fileSize: The actual number of bytes downloaded (post-check). Lets
            STTService update row metadata after download.
        mimeType: Detected MIME type, if any. Informational only; PyAV decides
            whether the bytes contain a decodable audio stream.
    """

    data: bytes
    fileSize: int
    mimeType: Optional[str] = None


STTMediaLoader: TypeAlias = Callable[[int], Awaitable[STTLoaderResult]]
"""Service-supplied async loader. Receives maxBytes; returns STTLoaderResult.

Closes over platform identifiers and current SAVE_ATTACHMENTS behavior; lives
entirely outside lib/stt (``docs/plans/lib-stt-v1.md`` §1, dependency-firewall
seam #2).
"""
