"""lib.stt — provider-neutral Speech-to-Text library.

This package owns no DB rows, no bot state, no admission/concurrency policy, and
no config reading; it sits alongside other bot-free libraries (``lib/ai``,
``lib/markdown``, ``lib/yandex_search``) and MUST NOT import ``internal.bot``,
``internal.database``, or any singleton service. See
``docs/plans/lib-stt-v1.md`` §1 for the dependency firewall.

Public surface (complete per ``docs/plans/lib-stt-v1.md`` §3): data models
(:mod:`lib.stt.models`), the typed extraction exception taxonomy
(:mod:`lib.stt.exceptions`), the pure transcript formatter
(:mod:`lib.stt.formatter`), the abstract provider interface
(:mod:`lib.stt.abstract`), the PyAV-based audio extraction with format
negotiation (:func:`lib.stt.audio.extractAudio`), and the concrete Yandex
SpeechKit v3 provider
(:class:`lib.stt.providers.yandex_speechkit.YandexSpeechKitProvider`). The
provider is held directly by the integration layer (the future STTService).
"""

from lib.stt.abstract import AbstractSTTProvider
from lib.stt.audio import extractAudio
from lib.stt.exceptions import (
    AudioDecodeError,
    EncoderError,
    NoAudioTrackError,
    STTExtractionError,
)
from lib.stt.formatter import UNTRUSTED_TRANSCRIPT_HEADER, formatTranscript
from lib.stt.models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAudioContainerType,
    STTErrorCode,
    STTResultStatus,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
)
from lib.stt.providers.yandex_speechkit import YandexSpeechKitProvider

__all__ = [
    # Abstract interface
    "AbstractSTTProvider",
    # Concrete providers
    "YandexSpeechKitProvider",
    # Audio extraction
    "extractAudio",
    # Exceptions
    "STTExtractionError",
    "NoAudioTrackError",
    "AudioDecodeError",
    "EncoderError",
    # Enums
    "STTResultStatus",
    "STTErrorCode",
    "STTAudioContainerType",
    # Records
    "TranscriptionWord",
    "TranscriptionSegment",
    "TranscriptionResult",
    "AudioFormatSpec",
    "ExtractedAudio",
    # Formatter
    "formatTranscript",
    "UNTRUSTED_TRANSCRIPT_HEADER",
]
