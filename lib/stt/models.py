"""Provider-neutral data models for the lib.stt Speech-to-Text library.

This module is the pure-data foundation of ``lib/stt``: it defines the enums,
immutable records, and the typed media-loader boundary used across the whole
STT pipeline. It deliberately imports only the standard library (``enum``,
``dataclasses``, ``typing``) and MUST NOT import ``internal.bot``,
``internal.database``, any singleton service, or ``lib.stt.exceptions`` (the
exception module imports this one, not the reverse — see the dependency
firewall in ``docs/design/lib-stt-v1.md`` §1).

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

See ``docs/design/lib-stt-v1.md`` §4 for the authoritative prose on every type.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Optional


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

    Ownership after the stateless-Service refactor:

    - **STTService** produces: ``STT_DISABLED``, ``SOURCE_TOO_LARGE``.
    - **Provider** returns inside ``TranscriptionResult(ERROR, …)``:
      ``NO_AUDIO``, ``PROVIDER_ERROR``, ``PROTOCOL_ERROR``,
      ``OBJECT_STORAGE_ERROR``.
    - **Provider also surfaces** ``SOURCE_TOO_LARGE`` when the extracted
      payload exceeds the inline threshold and Object Storage is disabled.
    - **Reserved for the future handler round** (STTService is now stateless
      and does not download/bound duration):
      ``SOURCE_SIZE_UNKNOWN``, ``DOWNLOAD_ERROR``, ``DURATION_EXCEEDED``.
    """

    STT_DISABLED = "stt-disabled"
    """STT is disabled for this chat (``[stt].enabled = false``).

    Produced by STTService; never produced inside lib/stt.
    """

    SOURCE_TOO_LARGE = "source-too-large"
    """Source byte length (``len(data)``) exceeded ``maxSourceBytes``, or
    extracted payload (``len(audio.data)``) exceeded ``maxInlineBytes`` with
    Object Storage disabled.

    Produced by ``STTService`` (source-byte cap) and surfaced by the Yandex
    provider when ``len(audio.data) >= maxInlineBytes`` and Object Storage is
    disabled (design §4.2/§4.5).
    """

    SOURCE_SIZE_UNKNOWN = "source-size-unknown"
    """Source size could not be determined before download.

    Reserved for the future handler round — STTService is stateless and does
    not download media.
    """

    NO_AUDIO = "no-audio"
    """Source contained no decodable audio stream.

    Produced by the provider (returned inside ``TranscriptionResult(ERROR, …)``).
    """

    DURATION_EXCEEDED = "duration-exceeded"
    """Decoded duration exceeded the configured duration cap.

    Reserved for the future handler round — STTService is stateless and does
    not measure duration.
    """

    DOWNLOAD_ERROR = "download-error"
    """Media download failed.

    Reserved for the future handler round — STTService is stateless and does
    not download media.
    """

    PROVIDER_ERROR = "provider-error"
    """Provider operation error (auth/429/5xx/timeout) or decoder/muxer failure.

    Produced by the provider.  Also serves as STTService's catch-all fallback
    for unexpected exceptions.
    """

    PROTOCOL_ERROR = "protocol-error"
    """Malformed provider response, trailing garbage, or streamed result body over the result-byte cap.

    Produced by the provider.
    """

    OBJECT_STORAGE_ERROR = "object-storage-error"
    """Object Storage upload failure (bucket/credentials/network).

    Provider-owned group (alongside ``PROVIDER_ERROR`` / ``PROTOCOL_ERROR``).
    Surfaced by the Yandex provider when the co-located
    ``YandexObjectStorage.upload()`` raises before submit (design §4.3/§4.5).
    A best-effort delete failure does NOT surface as this code (swallowed by
    the wrapper).
    """


class STTAudioContainerType(StrEnum):
    """Audio containers a provider accepts inline."""

    WAV = "wav"
    """WAV container (PCM with a RIFF header)."""

    OGG_OPUS = "ogg-opus"
    """Ogg container with an Opus codec (Telegram VOICE native shape)."""

    MP3 = "mp3"
    """MPEG-1/2 Audio Layer III container (common AUDIO shape)."""

    def toYandexSpeechKit(self) -> str:
        match self:
            case STTAudioContainerType.WAV:
                return "WAV"
            case STTAudioContainerType.OGG_OPUS:
                return "OGG_OPUS"
            case STTAudioContainerType.MP3:
                return "MP3"
            case _:
                raise ValueError(f"Unsupported STTAudioContainerType: {self}")


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
    words: Sequence[TranscriptionWord]


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Provider-neutral result of one transcription attempt.

    Attributes:
        status: The outcome category.
        segments: Immutable tuple of TranscriptionSegment; empty unless FINAL.
        errorCode: Present iff status == ERROR; identifies the failure category.
    """

    status: STTResultStatus
    segments: Sequence[TranscriptionSegment]
    errorCode: Optional[STTErrorCode] = None


@dataclass(frozen=True, slots=True)
class AudioFormatSpec:
    """One container format a provider accepts inline.

    Describes the negotiation surface used by ``audio.py`` to decide pass-through
    vs. transcode. Does NOT describe recognition quality — quality-by-format is
    UNVERIFIED (see ``docs/design/lib-stt-v1.md`` §10(b)); the proven win is
    payload size/traffic.

    Attributes:
        container: The accepted container.
        minChannels: Minimum accepted channel count (inclusive).
        maxChannels: Maximum accepted channel count (inclusive). SpeechKit
            accepts multi-channel async audio, but the exact ceiling is
            unpublished; set a generous value here and let the decoded-buffer
            cap (``docs/design/lib-stt-v1.md`` §5) bound the actual multi-channel
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
    downmixed (hard rule, ``docs/design/lib-stt-v1.md`` §5).

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
