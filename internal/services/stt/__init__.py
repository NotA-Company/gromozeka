"""STT service — bot-side integration of lib/stt.

Provides :class:`STTService` (singleton), the integration-boundary
dataclasses :class:`STTMediaRequest` and :class:`STTOutcome`, and wires the
configured provider (currently ``YandexSpeechKitProvider``) into the
application lifecycle.

Usage::

    from internal.services.stt import STTService, STTMediaRequest, STTOutcome
"""

from internal.services.stt.service import STTMediaRequest, STTOutcome, STTService

__all__ = ["STTMediaRequest", "STTOutcome", "STTService"]
