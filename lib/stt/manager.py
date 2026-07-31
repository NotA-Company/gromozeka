"""STTManager — selects the single configured STT provider and owns its lifecycle.

This module implements :class:`STTManager`, the provider-neutral orchestrator for
``lib/stt``. It is structurally analogous to :class:`lib.ai.manager.LLMManager`
(holds the provider(s), owns ``aclose()``) but selects **one** configured provider
rather than a registry — see ``docs/plans/lib-stt-v1.md`` §8 (authoritative) and §1
(the dependency firewall). There is exactly one active provider per manager instance.

Dependency firewall (load-bearing contract #1, §1). The manager receives its
already-constructed provider at construction (INJECTED from outside by the future
``STTService`` integration layer); it does **not** read ``[stt]`` config, does **not**
call ``ProxyService.resolveProxy``, and does **not** import ``internal.bot``,
``internal.database``, or any singleton service. Provider resolution (config parse →
``YandexSpeechKitProvider(...)`` with a resolved :class:`~lib.proxy.ProxyConfig`)
happens in the service layer, exactly the way the proxy is injected into the provider.

The manager does **not** do audio extraction or transcript formatting — it only
delegates transcription to the selected provider. ``audio.extractAudio`` +
``formatter.formatTranscript`` are called by the integration layer
(``STTService`` / handlers), never here (§5 owns extraction; §6 owns formatting).

Raise/return contract (load-bearing contract #2, §4/§8): the selected provider's
``transcribe`` returns a :class:`~lib.stt.models.TranscriptionResult` for **every**
expected outcome, including failures — it never raises. The manager trusts that
contract and delegates without an extra try/except: an unexpected provider raise
propagates to ``STTService`` (the final never-raise boundary, §4). ``aclose`` is the
one place the manager defends — a provider close failure must not block graceful
shutdown (parent §11.3).
"""

import logging

from lib.stt.abstract import AbstractSTTProvider
from lib.stt.models import ExtractedAudio, TranscriptionResult

logger = logging.getLogger(__name__)
"""Module logger (mirrors :mod:`lib.yandex_search.client` — no logger injection)."""


class STTManager:
    """Provider-neutral STT orchestrator holding the single selected provider.

    Holds exactly one :class:`~lib.stt.abstract.AbstractSTTProvider` (the one the
    integration layer resolved and injected) and delegates
    :meth:`~AbstractSTTProvider.transcribe` to it. Unlike
    :class:`~lib.ai.manager.LLMManager`, there is no registry, no model→provider
    lookup, and no ``getProvider`` discovery surface — the manager is a thin
    lifecycle/delegation holder for the one configured provider (§8: "selects ONE
    configured provider instead of a registry").

    The provider is owned for the manager's lifetime: :meth:`aclose` closes the
    provider's persistent HTTP client (e.g. the ``httpx.AsyncClient``) and is
    best-effort — a close failure is logged, not propagated, so graceful shutdown
    always completes (parent §11.3).

    Attributes:
        _provider: The single selected, injected provider this manager delegates to.
    """

    def __init__(self, provider: AbstractSTTProvider) -> None:
        """Initialize the manager with the single selected provider.

        The provider is injected already-constructed (the dependency firewall, §1):
        the integration layer resolves config + proxy, builds the provider, and hands
        it in. The manager neither reads config nor resolves the proxy.

        Args:
            provider: The single selected :class:`~lib.stt.abstract.AbstractSTTProvider`
                to hold and delegate transcription to. Must be a concrete
                ``AbstractSTTProvider`` instance.

        Raises:
            TypeError: If ``provider`` is not an :class:`~lib.stt.abstract.AbstractSTTProvider`
                instance (defensive guard — a non-provider cannot satisfy the
                delegation/lifecycle contract).

        Returns:
            None
        """
        if not isinstance(provider, AbstractSTTProvider):
            raise TypeError(f"provider must be an AbstractSTTProvider instance, got {type(provider).__name__}")
        self._provider: AbstractSTTProvider = provider

    @property
    def provider(self) -> AbstractSTTProvider:
        """The single selected provider this manager delegates to.

        Exposed so the integration layer (and ``audio.py``'s format negotiation, which
        reads ``supportedInputFormats``) can reach the active provider without a registry
        lookup. Read-only — the selected provider is fixed for the manager's lifetime.

        Returns:
            AbstractSTTProvider: The held provider.
        """
        return self._provider

    async def transcribe(self, audio: ExtractedAudio) -> TranscriptionResult:
        """Delegate transcription to the single selected provider.

        The manager itself does NOT extract audio or format the transcript (§5 owns
        extraction, §6 owns formatting); it forwards the already-negotiated
        :class:`~lib.stt.models.ExtractedAudio` to the provider. Per the
        :meth:`~AbstractSTTProvider.transcribe` contract (§4/§8), the provider returns a
        :class:`~lib.stt.models.TranscriptionResult` for every expected outcome —
        including failures — and never raises for expected provider/transport/protocol
        failures. The manager trusts that contract; an unexpected provider raise
        propagates to ``STTService`` (the final never-raise boundary).

        Args:
            audio: The format-aware audio after negotiation (the source container on a
                pass-through path, or the transcode target — e.g. ``OGG_OPUS`` — on a
                transcode path). Passed through unchanged to the provider.

        Returns:
            TranscriptionResult: Whatever the selected provider returns (FINAL /
            NO_SPEECH / ERROR).
        """
        return await self._provider.transcribe(audio)

    async def aclose(self) -> None:
        """Close the selected provider's persistent resources, best-effort.

        Called during graceful shutdown, after the queue has drained in-flight STT
        workers (parent §11.3). The close is best-effort: if the provider's ``aclose``
        raises, the exception is logged and NOT propagated, so shutdown is never blocked
        by a provider close failure. The underlying provider close (e.g.
        ``httpx.AsyncClient.aclose``) is itself idempotent, so calling this more than
        once is safe.

        Returns:
            None
        """
        try:
            await self._provider.aclose()
        except Exception:  # noqa: BLE001 — best-effort shutdown must never raise
            logger.exception(
                "STTManager: provider %s aclose raised during shutdown; suppressing to complete graceful shutdown",
                type(self._provider).__name__,
            )
