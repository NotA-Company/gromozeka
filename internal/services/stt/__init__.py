"""STT service — bot-side integration of lib/stt.

Provides :class:`STTService` (singleton) and the integration-boundary
dataclass :class:`STTOutcome`, and wires the configured provider (currently
``YandexSpeechKitProvider``) into the application lifecycle.

Usage::

    from internal.services.stt import STTService, STTOutcome
"""

from .service import STTOutcome, STTService

__all__ = ["STTOutcome", "STTService"]
