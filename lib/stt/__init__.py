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
negotiation (:func:`lib.stt.audio.extractAudio`), the provider-neutral manager
that selects the single configured provider (:class:`lib.stt.manager.STTManager`),
and the concrete Yandex SpeechKit v3 provider
(:class:`lib.stt.providers.yandex_speechkit.YandexSpeechKitProvider`).

The package imports cleanly without PyAV present (the guarded import in
:mod:`lib.stt.audio` defers all PyAV work behind the ``_PYAV_AVAILABLE`` flag);
when STT is enabled, missing PyAV is a startup error raised by the integration
layer, not by importing this package.
"""

from lib.stt.abstract import AbstractSTTProvider
from lib.stt.audio import extractAudio
from lib.stt.exceptions import (
    AudioDecodeError,
    AudioTooLargeError,
    DurationExceededError,
    EncoderError,
    NoAudioTrackError,
    SourceTooLargeError,
    STTExtractionError,
)
from lib.stt.formatter import UNTRUSTED_TRANSCRIPT_HEADER, formatTranscript
from lib.stt.manager import STTManager
from lib.stt.models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAudioContainerType,
    STTErrorCode,
    STTLoaderResult,
    STTMediaLoader,
    STTResultStatus,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
)
from lib.stt.providers.yandex_speechkit import YandexSpeechKitProvider

__all__ = [
    # Abstract interface
    "AbstractSTTProvider",
    # Manager (selects the single configured provider, owns aclose)
    "STTManager",
    # Concrete providers
    "YandexSpeechKitProvider",
    # Audio extraction
    "extractAudio",
    # Exceptions
    "STTExtractionError",
    "NoAudioTrackError",
    "SourceTooLargeError",
    "DurationExceededError",
    "AudioTooLargeError",
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
    "STTLoaderResult",
    # Type aliases
    "STTMediaLoader",
    # Formatter
    "formatTranscript",
    "UNTRUSTED_TRANSCRIPT_HEADER",
]
