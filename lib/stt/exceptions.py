"""Typed audio-extraction exception taxonomy for lib.stt.

Defines the exception hierarchy raised by ``lib.stt.audio.extractAudio()`` —
the only runtime raise-point inside ``lib/stt`` (load-bearing contract #2 in
``docs/plans/lib-stt-v1.md`` §4/§5). Each concrete exception sets a class-level
``errorCode`` (an :class:`~lib.stt.models.STTErrorCode`) that identifies the
failure category, so ``STTService`` can map the exception to the correct
``FAILED`` category without re-mapping.

This module imports :mod:`lib.stt.models` (for ``STTErrorCode``); ``models`` MUST
NOT import this module (the dependency runs one way only — see the dependency
firewall in ``docs/plans/lib-stt-v1.md`` §1).
"""

from .models import STTErrorCode


class STTExtractionError(Exception):
    """Base for all typed audio-extraction failures raised by lib.stt.audio.

    Every concrete subclass sets a class-level ``errorCode`` identifying the
    failure category, so a caller can read ``exc.errorCode`` to obtain the
    provider-neutral :class:`STTErrorCode` without re-mapping the exception
    type. Multiple exception types may share one code (e.g.
    :class:`AudioDecodeError` and :class:`EncoderError` both map to
    ``PROVIDER_ERROR``).

    Attributes:
        errorCode: The provider-neutral failure category for this exception
            type. Declared on the base (never instantiated directly) and set to
            a concrete value by every subclass.
    """

    errorCode: STTErrorCode

    def __init__(self, message: str) -> None:
        """Initialize the error with a human-readable message.

        Args:
            message: Human-readable description of the failure, forwarded to
                :class:`Exception`.

        Returns:
            None
        """
        super().__init__(message)


class NoAudioTrackError(STTExtractionError):
    """Raised when the source contains no decodable audio stream.

    Maps to :attr:`STTErrorCode.NO_AUDIO`.
    """

    errorCode = STTErrorCode.NO_AUDIO


class AudioDecodeError(STTExtractionError):
    """Raised on a corrupt/truncated source or a decoder failure during probing.

    Maps to :attr:`STTErrorCode.PROVIDER_ERROR` (shared with
    :class:`EncoderError` — two exception types, one code).
    """

    errorCode = STTErrorCode.PROVIDER_ERROR


class EncoderError(STTExtractionError):
    """Raised on an encoder/muxer failure (pcm_s16le / libopus / libmp3lame).

    Maps to :attr:`STTErrorCode.PROVIDER_ERROR` (shared with
    :class:`AudioDecodeError` — two exception types, one code).
    """

    errorCode = STTErrorCode.PROVIDER_ERROR
