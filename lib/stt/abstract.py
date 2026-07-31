"""Abstract provider-neutral STT provider interface for lib.stt.

Defines :class:`AbstractSTTProvider`, the interface every concrete Speech-to-Text
provider (e.g. ``YandexSpeechKitProvider``) implements. It is consumed by
``STTManager`` (which selects the single configured provider) and by
``audio.py`` (which reads :attr:`AbstractSTTProvider.supportedInputFormats` to
negotiate pass-through vs. transcode).

This module imports only the standard library (``abc``, ``typing``) and
:mod:`lib.stt.models` — no ``internal.*`` or singleton-service imports (the
``lib/stt`` dependency firewall, ``docs/plans/lib-stt-v1.md`` §1).
"""

from abc import ABC, abstractmethod
from typing import Tuple

from lib.stt.models import AudioFormatSpec, ExtractedAudio, TranscriptionResult


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

    @property
    @abstractmethod
    def supportedInputFormats(self) -> Tuple[AudioFormatSpec, ...]:
        """Ordered container formats this provider accepts inline.

        Consumed by ``audio.py`` for pass-through/transcode negotiation. The
        FIRST entry is the provider's preferred transcode target (e.g.
        ``OGG_OPUS`` for Yandex). Does NOT describe recognition quality
        (quality-by-format is UNVERIFIED, §10(b)).

        Returns:
            Tuple[AudioFormatSpec, ...]: The provider's ordered accepted input
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

    @abstractmethod
    async def aclose(self) -> None:
        """Release provider resources (e.g. close the persistent httpx client).

        Called by ``STTManager.aclose()`` during graceful shutdown, after the
        queue has drained in-flight STT workers (parent §11.3).

        Returns:
            None
        """
