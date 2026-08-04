"""STT service — stateless singleton wrapping the STT provider lifecycle.

Constructs (or skips) the configured provider at startup, resolves its proxy
via :class:`~internal.services.proxy.service.ProxyService`, and closes it on
shutdown.  The transcription pipeline (``transcribeMedia``) is a thin
never-raise wrapper: size gate → rate limiters → semaphore → provider call
→ outcome mapping.  The service does not touch the database; the handler
owns the full row lifecycle.

Provider configuration lives under the ``[stt]`` TOML section and is
accessed via :meth:`~internal.config.manager.ConfigManager.getSttConfig`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from threading import RLock
from typing import Any, Dict, Optional

import lib.utils as libUtils
from internal.config.manager import ConfigManager
from internal.services.proxy.service import ProxyService
from lib.proxy import ProxyConfig
from lib.rate_limiter.manager import RateLimiterManager
from lib.stt import (
    AbstractSTTProvider,
    STTErrorCode,
    STTResultStatus,
    TranscriptionResult,
    YandexSpeechKitProvider,
)

from .formatter import formatTranscript

logger = logging.getLogger(__name__)


STT_PROVIDERS_MAP = {
    "yandex-speechkit": YandexSpeechKitProvider,
}

# ---------------------------------------------------------------------------
# Integration-boundary dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class STTOutcome:
    """Immutable result of a single transcription attempt.

    Produced by :meth:`STTService.transcribeMedia` and consumed by the
    handler to decide how to update the media-attachment row.

    Attributes:
        success: ``True`` when a transcript was produced,
            ``False`` on any error.
        description: The formatted transcript text when ``success`` is
            ``True``; ``None`` when ``False``.
        errorCode: Present iff ``success`` is ``False``; identifies the
            failure category from :class:`~lib.stt.models.STTErrorCode`.
    """

    success: bool
    description: Optional[str] = None
    errorCode: Optional[STTErrorCode] = None


# ---------------------------------------------------------------------------
# STTService singleton
# ---------------------------------------------------------------------------


class STTService:
    """Stateless singleton that owns the STT provider lifecycle.

    Mirrors :class:`~internal.services.proxy.service.ProxyService` exactly:
    class-level ``_instance`` / ``_lock``, ``__new__`` create-or-return,
    ``getInstance()`` classmethod, ``hasattr(self, 'initialized')`` guard,
    and a separate ``initialize(...)`` method that receives config at
    application startup.

    The service does not touch the database; the handler owns the full
    row lifecycle.

    Usage::

        STTService.getInstance().initialize(configManager)
        if STTService.getInstance().isEnabled():
            ...

    Attributes:
        _provider: The constructed :class:`~lib.stt.abstract.AbstractSTTProvider`,
            or ``None`` when STT is disabled.
        _enabled: Whether the ``[stt] enabled = true`` flag is set and
            the provider was constructed successfully.
        _semaphore: Concurrency limiter for in-flight transcriptions.
        _maxSourceBytes: Maximum source-data size in bytes (pre-admission
            rejection).
        _chatLimiterQueue: Rate-limiter queue name for per-chat STT
            throttling, or ``None`` if not configured.
        _globalLimiterQueue: Rate-limiter queue name for global STT
            throttling, or ``None`` if not configured.
    """

    _instance: Optional["STTService"] = None
    _lock = RLock()

    def __new__(cls) -> "STTService":
        """Create or return the singleton instance.

        Returns:
            The singleton STTService instance.
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    @classmethod
    def getInstance(cls) -> "STTService":
        """Get or create the singleton STTService instance.

        Returns:
            The singleton STTService instance.
        """
        if cls._instance is None:
            return cls()
        return cls._instance

    def __init__(self) -> None:
        """Initialise the STT service.

        Only the first call executes; subsequent calls are guarded by
        the ``hasattr(self, 'initialized')`` sentinel.  Does NOT read
        config — that happens in :meth:`initialize`.
        """
        if hasattr(self, "initialized"):
            return

        self.initialized = True
        self._provider: Optional[AbstractSTTProvider] = None
        self._enabled: bool = False
        self._initialized: bool = False
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._maxSourceBytes: int = 0
        self._chatLimiterQueue: Optional[str] = None
        self._globalLimiterQueue: Optional[str] = None

    def initialize(self, configManager: ConfigManager) -> None:
        """Initialise the STT service with configuration.

        Reads the ``[stt]`` config section.  When ``enabled`` is ``false``
        (the default), the provider is ``None`` and the service is a no-op.
        When ``enabled`` is ``true``, validates the provider name, resolves
        the proxy, and constructs the provider (which validates its own
        parameters — credentials, placeholders, numeric caps, cross-field
        constraints).

        Idempotent — subsequent calls after the first successful
        initialisation are silently skipped.

        Args:
            configManager: The application configuration manager.

        Raises:
            ValueError: If the provider name is unknown (not in
                ``STT_PROVIDERS_MAP``).  Propagates ``ValueError`` from the
                provider constructor (missing/empty credentials, unresolved
                ``${…}`` placeholders, non-positive numeric caps,
                ``maxPollIntervalSeconds < pollIntervalSeconds``) and from
                ``ProxyService.resolveProxy``.
        """
        if self._initialized:
            logger.debug("STTService already initialized; skipping.")
            return

        sttConfig: Dict[str, Any] = configManager.getSttConfig()
        enabled: bool = bool(sttConfig.get("enabled", False))

        if not enabled:
            self._provider = None
            self._enabled = False
            self._initialized = True
            logger.info("STT service disabled (stt.enabled = false).")
            return

        # --- Validation (the ONLY permitted raise site) -------------------
        provider: str = str(sttConfig.get("provider", ""))

        if provider not in STT_PROVIDERS_MAP:
            raise ValueError(
                f"STT: unknown provider '{provider}'. Supported providers: {list(STT_PROVIDERS_MAP.keys())}"
            )

        # --- Proxy resolution -------------------------------------------
        proxyConfig: ProxyConfig = ProxyService.getInstance().resolveProxy(sttConfig, "stt")

        # --- Provider construction ----------------------------------------
        self._provider = STT_PROVIDERS_MAP[provider](
            proxyConfig=proxyConfig,
            **{
                libUtils.kebabToCamelCase(k): v
                for k, v in sttConfig.items()
                if k not in ("enabled", "use-proxy", "proxy-config", "provider")
            },
        )

        # --- Service caps (stored now, consumed by transcribeMedia) ------
        self._semaphore = asyncio.Semaphore(int(sttConfig.get("max-concurrency", 2)))
        self._maxSourceBytes = int(sttConfig.get("max-source-bytes", 1073741824))

        self._chatLimiterQueue = (
            str(sttConfig["chat-ratelimiter-queue"]) if "chat-ratelimiter-queue" in sttConfig else None
        )
        self._globalLimiterQueue = (
            str(sttConfig["global-ratelimiter-queue"]) if "global-ratelimiter-queue" in sttConfig else None
        )

        # Provider successfully constructed — mark enabled and initialized.
        self._enabled = True
        self._initialized = True
        logger.info("STT service initialized (provider=yandex-speechkit).")

    def isEnabled(self) -> bool:
        """Whether the STT service is enabled.

        Returns:
            ``True`` if ``[stt] enabled = true`` and validation passed.
        """
        return self._enabled

    async def aclose(self) -> None:
        """Close the provider's persistent HTTP client (graceful shutdown).

        Best-effort: no-op when the service is disabled or the provider
        is ``None``.  Never raises.
        """
        if self._provider is not None:
            try:
                await self._provider.aclose()
                logger.info("STT provider closed.")
            except Exception:  # noqa: BLE001 — best-effort shutdown
                logger.exception("Error closing STT provider during shutdown")

    async def transcribeMedia(self, data: bytes, *, chatId: Optional[int]) -> STTOutcome:
        """Transcribe raw audio bytes through the provider.

        Thin never-raise pipeline: ``STT_DISABLED`` early return when
        disabled; ``SOURCE_TOO_LARGE`` when ``len(data) > maxSourceBytes``;
        per-chat and global rate limiters; concurrency semaphore;
        ``await self._provider.stt(data)``; ``_mapOutcome`` (FINAL /
        NO_SPEECH → ``DONE`` + ``formatTranscript``; ERROR → ``FAILED`` +
        ``errorCode``).  NEVER raises (except ``asyncio.CancelledError``).

        Args:
            data: Raw audio bytes to transcribe.
            chatId: Chat ID for per-chat rate limiting, or ``None`` to skip
                the per-chat limiter.

        Returns:
            STTOutcome: ``status=DONE`` with the formatted transcript on
            success or no speech; ``status=FAILED`` with an ``errorCode``
            on any error path.

        Raises:
            asyncio.CancelledError: Propagated, never caught.
        """
        if not self._enabled:
            return STTOutcome(success=False, description=None, errorCode=STTErrorCode.STT_DISABLED)
        if len(data) > self._maxSourceBytes:
            return STTOutcome(success=False, description=None, errorCode=STTErrorCode.SOURCE_TOO_LARGE)

        try:
            # ------------------------------------------------------------------
            # Step 5: Admission (semaphore + limiters + timeout)
            # ------------------------------------------------------------------
            if self._chatLimiterQueue is not None and chatId is not None:
                await RateLimiterManager.getInstance().applyLimit(self._chatLimiterQueue, key=str(chatId))
            if self._globalLimiterQueue is not None:
                await RateLimiterManager.getInstance().applyLimit(self._globalLimiterQueue)
            # Concurrency semaphore.

            assert self._semaphore is not None, "transcribeMedia: _semaphore is None"
            async with self._semaphore:
                # --------------------------------------------------------------
                # Step 8: Provider call
                # --------------------------------------------------------------
                try:
                    assert self._provider is not None, "transcribeMedia: _provider is None"
                    result: TranscriptionResult = await self._provider.stt(data)
                except Exception:  # noqa: BLE001 — provider never-raise defense-in-depth
                    logger.exception("transcribeMedia: unexpected provider exception")
                    return STTOutcome(success=False, description=None, errorCode=STTErrorCode.PROVIDER_ERROR)

                # --------------------------------------------------------------
                # Step 9: mapOutcome
                # --------------------------------------------------------------
                return self._mapOutcome(result)

        except Exception:  # noqa: BLE001 — never-raise boundary
            logger.exception("Unexpected exception in transcribeMedia")
            return STTOutcome(success=False, description=None, errorCode=STTErrorCode.PROVIDER_ERROR)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _mapOutcome(self, result: TranscriptionResult) -> STTOutcome:
        """Map a ``TranscriptionResult`` to an ``STTOutcome``.

        ``ERROR`` → ``FAILED`` with the provider's error code.
        ``FINAL`` / ``NO_SPEECH`` → ``DONE`` with the formatted transcript.

        Args:
            result: The provider's transcription result.

        Returns:
            STTOutcome: ``DONE`` with the formatted transcript, or ``FAILED``
            with the provider's error code.
        """
        if result.status == STTResultStatus.ERROR:
            return STTOutcome(success=False, description=None, errorCode=result.errorCode)
        description = formatTranscript(result)
        return STTOutcome(success=True, description=description)
