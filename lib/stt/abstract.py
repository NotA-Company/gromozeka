"""Abstract provider-neutral STT provider interface for lib.stt.

Defines :class:`AbstractSTTProvider`, the interface every concrete Speech-to-Text
provider (e.g. ``YandexSpeechKitProvider``) implements. It is held directly by
the integration layer (the future STTService, which owns the single configured
provider and its lifecycle) and consumed by ``audio.py`` (which reads
:attr:`AbstractSTTProvider.supportedInputFormats` to negotiate pass-through vs.
transcode).

This module imports only the standard library (``abc``, ``logging``,
``collections.abc``) and :mod:`lib.stt.models` / :mod:`lib.stt.exceptions` — no
``internal.*`` or singleton-service imports (the ``lib/stt`` dependency firewall,
``docs/design/lib-stt-v1.md`` §1).
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence

from . import audio
from .exceptions import STTExtractionError
from .models import AudioFormatSpec, ExtractedAudio, STTErrorCode, STTResultStatus, TranscriptionResult

logger = logging.getLogger(__name__)
"""Module logger for the never-raise defense-in-depth boundary in :meth:`stt`."""


class AbstractSTTProvider(ABC):
    """Provider-neutral Speech-to-Text provider interface.

    A concrete provider owns one persistent HTTP client (e.g. an
    ``httpx.AsyncClient`` configured with the injected, already-resolved
    :class:`~lib.proxy.ProxyConfig`) and exposes exactly three members: the
    ordered accepted input formats (consumed by ``audio.py`` for format
    negotiation), the async ``transcribe`` entry point, and an ``aclose`` for
    resource release on shutdown.

    The raise/return contract (load-bearing contract #2, §4) is load-bearing
    here: ``transcribe`` returns a :class:`~lib.stt.models.TranscriptionResult`
    for **every** expected outcome, including failures — it never raises for
    expected provider/transport/protocol failures (those become
    ``TranscriptionResult(status=ERROR, errorCode=...)``). Constructors may raise
    on startup configuration validation when STT is enabled (§11.2).

    Caps (operation/request timeouts, poll delays, result-byte cap) and config
    (credentials, model, language, proxy) are supplied at construction, not on
    ``transcribe``.
    """

    @abstractmethod
    def supportedInputFormats(self) -> Sequence[AudioFormatSpec]:
        """Ordered container formats this provider accepts inline.

        Consumed by ``audio.py`` for pass-through/transcode negotiation. The
        FIRST entry is the provider's preferred transcode target (e.g.
        ``OGG_OPUS`` for Yandex). Does NOT describe recognition quality
        (quality-by-format is UNVERIFIED, §10(b)).

        Returns:
            Sequence[AudioFormatSpec]: The provider's ordered accepted input
            container formats.
        """

    @abstractmethod
    async def transcribe(self, audio: ExtractedAudio) -> TranscriptionResult:
        """Transcribe format-aware ExtractedAudio.

        Accepts :class:`~lib.stt.models.ExtractedAudio` ONLY — no separate
        ``audioFormat`` / ``withTimestamps`` / chat-settings arguments (the
        container travels inside ``ExtractedAudio.container``, not as a separate
        argument). Returns a :class:`~lib.stt.models.TranscriptionResult` for
        every expected outcome, including failures
        (``TranscriptionResult(status=ERROR, errorCode=...)``); **never raises**
        for expected provider/transport/protocol failures.

        Args:
            audio: The format-aware audio handed to the provider after
                negotiation (the source container on a pass-through path, or the
                transcode target — e.g. ``OGG_OPUS`` — on a transcode path).
                ``channels`` is always the source channel count (no downmix).

        Returns:
            TranscriptionResult: The provider-neutral outcome. FINAL with the
            recognized segments, NO_SPEECH when recognition produced no
            non-empty final segment, or ERROR with an
            :class:`~lib.stt.models.STTErrorCode` for an expected failure.
        """

    async def stt(self, data: bytes) -> TranscriptionResult:
        """High-level never-raise entry: extract + transcribe.

        Wraps :func:`lib.stt.audio.extractAudio` so that any extraction failure
        (a typed :class:`~lib.stt.exceptions.STTExtractionError` or an unexpected
        exception) is mapped to a ``TranscriptionResult(status=ERROR, …)`` instead
        of propagating, then delegates to :meth:`transcribe` (which is itself
        never-raise). This is the integration layer's convenience entry point and
        NEVER raises for any expected or unexpected failure.

        Args:
            data: The source audio bytes to extract and transcribe.

        Returns:
            TranscriptionResult: FINAL/NO_SPEECH on success, or ERROR with an
            :class:`~lib.stt.models.STTErrorCode` for any extraction or
            transcription failure (NO_AUDIO / PROVIDER_ERROR from extraction;
            PROVIDER_ERROR / PROTOCOL_ERROR from the provider).
        """
        try:
            audioData = await audio.extractAudio(
                data,
                supportedInputFormats=self.supportedInputFormats(),
            )
            return await self.transcribe(audioData)
        except STTExtractionError as exc:
            return TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=exc.errorCode)
        except Exception:  # noqa: BLE001 — never-raise boundary (defense-in-depth)
            logger.exception("Unexpected STT failure")
            return TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=STTErrorCode.PROVIDER_ERROR)

    @abstractmethod
    async def aclose(self) -> None:
        """Release provider resources (e.g. close the persistent httpx client).

        Called by the service layer (the future STTService) during graceful
        shutdown, after in-flight STT workers have drained (parent §11.3).

        Returns:
            None
        """
