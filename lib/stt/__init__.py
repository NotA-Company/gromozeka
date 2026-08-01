"""lib.stt — provider-neutral Speech-to-Text library.

This package owns no DB rows, no bot state, no admission/concurrency policy, and
no config reading; it sits alongside other bot-free libraries (``lib/ai``,
``lib/markdown``, ``lib/yandex_search``) and MUST NOT import ``internal.bot``,
``internal.database``, or any singleton service. See
``docs/plans/lib-stt-v1.md`` §1 for the dependency firewall.

Public surface (complete per ``docs/plans/lib-stt-v1.md`` §3): data models
(:mod:`lib.stt.models`), the typed extraction exception taxonomy
(:mod:`lib.stt.exceptions`), the abstract provider interface
(:mod:`lib.stt.abstract`), the PyAV-based audio extraction with format
negotiation (:func:`lib.stt.audio.extractAudio`), and the concrete Yandex
SpeechKit v3 provider
(:class:`lib.stt.providers.yandex_speechkit.YandexSpeechKitProvider`). The
provider is held directly by the integration layer (the future STTService).
"""

from .abstract import AbstractSTTProvider
from .audio import extractAudio
from .exceptions import (
    AudioDecodeError,
    EncoderError,
    NoAudioTrackError,
    STTExtractionError,
)
from .models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAudioContainerType,
    STTErrorCode,
    STTResultStatus,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
)
from .providers.yandex_speechkit import YandexSpeechKitProvider

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
]
