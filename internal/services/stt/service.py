"""STT service — singleton that owns the STT provider lifecycle and transcription pipeline.

Constructs (or skips) the configured provider at startup, resolves its proxy
via :class:`~internal.services.proxy.service.ProxyService`, and closes it on
shutdown.  The transcription pipeline (``transcribeMedia``) handles
request → admission → download+bounds → provider call → terminal persist,
with full error-path and success-path coverage via verified compare-and-set
transitions.

Provider configuration lives under the ``[stt]`` TOML section and is
accessed via :meth:`~internal.config.manager.ConfigManager.getSttConfig`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from threading import RLock
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from internal.config.manager import ConfigManager
from internal.database import Database
from internal.database.models import MediaStatus
from internal.models.shared_enums import MessageType
from internal.services.proxy.service import ProxyService
from lib.proxy import ProxyConfig
from lib.rate_limiter.manager import RateLimiterManager
from lib.stt.abstract import AbstractSTTProvider
from lib.stt.formatter import formatTranscript
from lib.stt.models import STTErrorCode, STTResultStatus, TranscriptionResult
from lib.stt.providers.yandex_speechkit import YandexSpeechKitProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Integration-boundary dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class STTMediaRequest:
    """Immutable request describing a media file to transcribe.

    Built by the handler layer and handed to
    :meth:`STTService.transcribeMedia` (Phase 3).  All fields are set at
    construction time; the service never mutates the request.

    Attributes:
        mediaId: ``file_unique_id`` — the DB primary key for the media
            attachment row.
        fileId: Platform ``file_id`` or URL used by the loader to
            download the media bytes.
        mediaType: Platform media type (VIDEO / VIDEO_NOTE / VOICE / AUDIO).
        chatId: Chat the media belongs to (used for per-chat rate limiting).
        declaredSize: Platform-declared file size in bytes, or ``None`` if
            unknown.  Used for pre-admission size rejection.
        loader: Async callable ``(maxBytes: int) -> bytes | None`` that
            downloads the media.  ``None`` means the download failed.
    """

    mediaId: str
    fileId: str
    mediaType: MessageType
    chatId: int
    declaredSize: Optional[int]
    loader: Callable[[int], Awaitable[Optional[bytes]]]


@dataclass(frozen=True, slots=True)
class STTOutcome:
    """Immutable result of a single transcription attempt.

    Produced by :meth:`STTService.transcribeMedia` (Phase 3) and consumed
    by the handler to update the media-attachment row in the database.

    Attributes:
        status: ``MediaStatus.DONE`` when a transcript was produced,
            ``MediaStatus.FAILED`` on any error.
        description: The formatted transcript text when ``status`` is
            ``DONE``; ``None`` when ``FAILED``.
        errorCode: Present iff ``status == FAILED``; identifies the
            failure category from :class:`~lib.stt.models.STTErrorCode`.
    """

    status: MediaStatus
    description: Optional[str] = None
    errorCode: Optional[STTErrorCode] = None


# ---------------------------------------------------------------------------
# STTService singleton
# ---------------------------------------------------------------------------


class STTService:
    """Singleton service that owns the STT provider lifecycle.

    Mirrors :class:`~internal.services.proxy.service.ProxyService` exactly:
    class-level ``_instance`` / ``_lock``, ``__new__`` create-or-return,
    ``getInstance()`` classmethod, ``hasattr(self, 'initialized')`` guard,
    and a separate ``initialize(...)`` method that receives config at
    application startup.

    Usage::

        STTService.getInstance().initialize(configManager, database)
        if STTService.getInstance().isEnabled():
            ...

    Attributes:
        _provider: The constructed :class:`~lib.stt.abstract.AbstractSTTProvider`,
            or ``None`` when STT is disabled.
        _database: The application :class:`~internal.database.Database` handle.
        _enabled: Whether the ``[stt] enabled = true`` flag is set and
            validation passed.
        _semaphore: Concurrency limiter for in-flight transcriptions
            (Phase 3).
        _maxSourceBytes: Maximum downloadable source size in bytes.
        _maxDurationSeconds: Maximum decoded audio duration in seconds.
        _maxTranscriptChars: Maximum persisted transcript length in
            characters.
        _admissionTimeoutSeconds: Seconds to wait for a semaphore slot
            before rejecting with ``ADMISSION_TIMEOUT``.
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
        self._database: Optional[Database] = None
        self._enabled: bool = False
        self._initialized: bool = False
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._maxSourceBytes: int = 0
        self._maxDurationSeconds: int = 0
        self._maxTranscriptChars: int = 0
        self._admissionTimeoutSeconds: int = 0
        self._chatLimiterQueue: Optional[str] = None
        self._globalLimiterQueue: Optional[str] = None

    def initialize(self, configManager: ConfigManager, database: Database) -> None:
        """Initialise the STT service with configuration and database.

        Reads the ``[stt]`` config section.  When ``enabled`` is ``false``
        (the default), the provider is ``None`` and the service is a no-op.
        When ``enabled`` is ``true``, validates credentials and provider
        name, resolves the proxy, and constructs the
        :class:`~lib.stt.providers.yandex_speechkit.YandexSpeechKitProvider`.

        Idempotent — subsequent calls after the first successful
        initialisation are silently skipped.

        Args:
            configManager: The application configuration manager.
            database: The application database handle.

        Raises:
            ValueError: When ``enabled`` is ``true`` but credentials are
                missing/empty, contain unresolved ``${…}`` placeholders,
                the provider name is unknown, any numeric cap is
                non-positive, or ``poll-max-delay < poll-initial-delay``.
        """
        if self._initialized:
            logger.debug("STTService already initialized; skipping.")
            return

        sttConfig: Dict[str, Any] = configManager.getSttConfig()
        enabled: bool = bool(sttConfig.get("enabled", False))
        self._database = database

        if not enabled:
            self._provider = None
            self._enabled = False
            self._initialized = True
            logger.info("STT service disabled (stt.enabled = false).")
            return

        # --- Validation (the ONLY permitted raise site) -------------------
        apiKey: str = str(sttConfig.get("api-key", ""))
        folderId: str = str(sttConfig.get("folder-id", ""))
        provider: str = str(sttConfig.get("provider", ""))

        if not apiKey:
            raise ValueError("STT: api-key is required when stt.enabled = true")
        if "${" in apiKey:
            raise ValueError(
                "STT: api-key contains an unresolved ${...} placeholder; "
                "set the environment variable or provide a literal value"
            )
        if not folderId:
            raise ValueError("STT: folder-id is required when stt.enabled = true")
        if "${" in folderId:
            raise ValueError(
                "STT: folder-id contains an unresolved ${...} placeholder; "
                "set the environment variable or provide a literal value"
            )
        if provider != "yandex-speechkit":
            raise ValueError(f"STT: unknown provider '{provider}'; only 'yandex-speechkit' is supported")

        # Validate numeric caps (counts — positive integers).
        intKeys = [
            "max-source-bytes",
            "max-duration-seconds",
            "max-transcript-chars",
            "max-concurrency",
            "admission-timeout",
            "max-result-bytes",
        ]
        for key in intKeys:
            value = sttConfig.get(key)
            if value is not None:
                intVal: int = int(value)
                if intVal <= 0:
                    raise ValueError(f"STT: {key} must be a positive integer, got {intVal}")

        # Validate timeout keys (seconds — positive floats).
        timeoutKeys = [
            "request-timeout",
            "operation-timeout",
            "poll-initial-delay",
            "poll-max-delay",
        ]
        for key in timeoutKeys:
            value = sttConfig.get(key)
            if value is not None:
                floatVal: float = float(value)
                if floatVal <= 0:
                    raise ValueError(f"STT: {key} must be a positive number, got {floatVal}")

        # Cross-field: poll-max-delay must be >= poll-initial-delay.
        pollInitial: float = float(sttConfig.get("poll-initial-delay", 2))
        pollMax: float = float(sttConfig.get("poll-max-delay", 10))
        if pollMax < pollInitial:
            raise ValueError(f"STT: poll-max-delay ({pollMax}) must be >= poll-initial-delay ({pollInitial})")

        # --- Proxy resolution -------------------------------------------
        proxyConfig: ProxyConfig = ProxyService.getInstance().resolveProxy(sttConfig, "stt")

        # --- Provider construction ----------------------------------------
        self._provider = YandexSpeechKitProvider(
            apiKey=apiKey,
            folderId=folderId,
            model=str(sttConfig.get("model", "general")),
            language=str(sttConfig.get("language", "ru-RU")),
            proxyConfig=proxyConfig,
            requestTimeoutSeconds=float(sttConfig.get("request-timeout", 30)),
            operationBudgetSeconds=float(sttConfig.get("operation-timeout", 180)),
            pollIntervalSeconds=float(sttConfig.get("poll-initial-delay", 2)),
            maxPollIntervalSeconds=float(sttConfig.get("poll-max-delay", 10)),
            maxResultBytes=int(sttConfig.get("max-result-bytes", 5242880)),
        )

        # --- Phase 3 caps (stored now, consumed by transcribeMedia) ------
        self._semaphore = asyncio.Semaphore(int(sttConfig.get("max-concurrency", 2)))
        self._maxSourceBytes = int(sttConfig.get("max-source-bytes", 67108864))
        self._maxDurationSeconds = int(sttConfig.get("max-duration-seconds", 600))
        self._maxTranscriptChars = int(sttConfig.get("max-transcript-chars", 48000))
        self._admissionTimeoutSeconds = int(sttConfig.get("admission-timeout", 20))

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

    _PERSIST_TERMINAL_MAX_RETRIES: int = 3
    """Maximum retries for verified terminal persist before giving up."""

    _PERSIST_TERMINAL_BACKOFF: float = 0.05
    """Seconds between verified-terminal-persist retries."""

    _CLAIM_ORDER: Tuple[MediaStatus, ...] = (MediaStatus.NEW, MediaStatus.PENDING, MediaStatus.FAILED, MediaStatus.DONE)
    """Status values tried in order when claiming a row for processing."""

    async def transcribeMedia(self, request: STTMediaRequest, *, gateEnabled: bool) -> STTOutcome:
        """Transcribe a media attachment end-to-end.

        Synchronous pipeline: request → admission → download+bounds →
        provider call → terminal persist.  NEVER raises (except
        ``asyncio.CancelledError``).  Every return path that did real work
        (claimed PENDING) terminalizes the row before returning,
        EXCEPT cache-hit (step 2) and gate-off (step 3) early returns.

        Args:
            request: The media request describing what to transcribe.
            gateEnabled: Whether the per-chat STT gate is enabled.

        Returns:
            STTOutcome: ``status=DONE`` with the formatted transcript on a
            successful transcription or a cache hit (step 2); ``status=DONE``
            with a ``None`` description when the gate is off and the row has
            no prior description (step 3 normalize); ``status=FAILED`` with an
            ``errorCode`` on any error path.

        Raises:
            asyncio.CancelledError: Propagated, never caught.
        """
        try:
            return await self._transcribeMediaInner(request, gateEnabled=gateEnabled)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — never-raise boundary
            logger.exception("Unexpected exception in transcribeMedia")
            return STTOutcome(status=MediaStatus.FAILED, description=None, errorCode=STTErrorCode.PROVIDER_ERROR)

    async def _transcribeMediaInner(self, request: STTMediaRequest, *, gateEnabled: bool) -> STTOutcome:
        """Inner body of the transcription pipeline (never-raise boundary is the caller).

        Args:
            request: The media request describing what to transcribe.
            gateEnabled: Whether the per-chat STT gate is enabled.

        Returns:
            STTOutcome: The transcription result.
        """
        assert self._database is not None, "transcribeMedia called before initialize"
        mediaId: str = request.mediaId
        repo = self._database.mediaAttachments

        # ------------------------------------------------------------------
        # Step 1: Read row; insert minimal NEW row if missing
        # ------------------------------------------------------------------
        row = await repo.getMediaAttachment(mediaId)
        if row is None:
            await repo.addMediaAttachment(
                fileUniqueId=mediaId,
                fileId=request.fileId,
                mediaType=request.mediaType,
                status=MediaStatus.NEW,
                description=None,
            )
            # Re-read after insert (handles concurrent-insert race).
            row = await repo.getMediaAttachment(mediaId)

        if row is None:
            # Should not happen — DB is broken.
            logger.error("transcribeMedia: media row disappeared after insert for %s", mediaId)
            return STTOutcome(status=MediaStatus.FAILED, description=None, errorCode=STTErrorCode.PROVIDER_ERROR)

        # ------------------------------------------------------------------
        # Step 2: Cache hit — terminal WITH description
        # ------------------------------------------------------------------
        if row["status"] == MediaStatus.DONE and row["description"] is not None:
            logger.debug("transcribeMedia: cache hit for %s", mediaId)
            return STTOutcome(status=MediaStatus.DONE, description=row["description"])

        # ------------------------------------------------------------------
        # Step 3: Gate off + no description → normalize to DONE/null
        # ------------------------------------------------------------------
        if not gateEnabled and row["description"] is None:
            logger.debug("transcribeMedia: gate off for %s, normalizing to DONE/null", mediaId)
            if row["status"] != MediaStatus.DONE:
                await repo.setStatusVerified(mediaId, expected=row["status"], target=MediaStatus.DONE, description=None)
            return STTOutcome(status=MediaStatus.DONE, description=None)

        # ------------------------------------------------------------------
        # Step 3a (pre-admission): declared size rejection
        # ------------------------------------------------------------------
        if request.declaredSize is not None and request.declaredSize > self._maxSourceBytes:
            logger.warning(
                "transcribeMedia: declared size %d > max %d for %s",
                request.declaredSize,
                self._maxSourceBytes,
                mediaId,
            )
            return STTOutcome(status=MediaStatus.FAILED, description=None, errorCode=STTErrorCode.SOURCE_TOO_LARGE)

        # ------------------------------------------------------------------
        # Step 4: Claim / orphan-reclaim → PENDING
        # ------------------------------------------------------------------
        claimed = False
        for expectedStatus in self._CLAIM_ORDER:
            claimResult = await repo.setStatusVerified(mediaId, expected=expectedStatus, target=MediaStatus.PENDING)
            if claimResult is not None:
                claimed = True
                break
        if not claimed:
            logger.error("transcribeMedia: unable to claim row %s to PENDING", mediaId)
            return STTOutcome(status=MediaStatus.FAILED, description=None, errorCode=STTErrorCode.PROVIDER_ERROR)

        # ------------------------------------------------------------------
        # Step 5: Admission (semaphore + limiters + timeout)
        # ------------------------------------------------------------------
        admissionError = await self._admit(request)
        if admissionError is not None:
            outcome = STTOutcome(status=MediaStatus.FAILED, description=None, errorCode=admissionError)
            await self._persistTerminal(mediaId, outcome)
            return outcome

        try:
            # --------------------------------------------------------------
            # Step 6: Download
            # --------------------------------------------------------------
            data, downloadError = await self._downloadAndBound(request)
            if downloadError is not None:
                outcome = STTOutcome(status=MediaStatus.FAILED, description=None, errorCode=downloadError)
                await self._persistTerminal(mediaId, outcome)
                return outcome

            # --------------------------------------------------------------
            # Step 7: Duration bound (not yet available — TODO Phase-future)
            # --------------------------------------------------------------

            # --------------------------------------------------------------
            # Step 8: Provider call
            # --------------------------------------------------------------
            try:
                assert self._provider is not None, "transcribeMedia: _provider is None"
                assert data is not None, "transcribeMedia: data is None after successful download"
                result: TranscriptionResult = await self._provider.stt(data)
            except Exception:  # noqa: BLE001 — provider never-raise defense-in-depth
                logger.exception("transcribeMedia: unexpected provider exception for %s", mediaId)
                outcome = STTOutcome(status=MediaStatus.FAILED, description=None, errorCode=STTErrorCode.PROVIDER_ERROR)
                await self._persistTerminal(mediaId, outcome)
                return outcome

            # --------------------------------------------------------------
            # Step 9: mapOutcome
            # --------------------------------------------------------------
            try:
                outcome = self._mapOutcome(result)
            except Exception:  # noqa: BLE001 — defensive: any formatter bug terminalizes the row
                logger.exception("transcribeMedia: unexpected error in _mapOutcome for %s", mediaId)
                outcome = STTOutcome(status=MediaStatus.FAILED, description=None, errorCode=STTErrorCode.PROVIDER_ERROR)
                await self._persistTerminal(mediaId, outcome)
                return outcome

            # --------------------------------------------------------------
            # Step 10: Terminal persist
            # --------------------------------------------------------------
            await self._persistTerminal(mediaId, outcome)

            # --------------------------------------------------------------
            # Step 11: Return
            # --------------------------------------------------------------
            return outcome
        finally:
            # Release the concurrency semaphore held by _admit.
            assert self._semaphore is not None
            self._semaphore.release()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _admit(self, request: STTMediaRequest) -> Optional[STTErrorCode]:
        """Acquire concurrency semaphore + rate limiters within the admission timeout.

        Returns ``None`` on successful admission — the caller holds the
        semaphore and MUST release it (via ``self._semaphore.release()``) when
        work is done.  Returns ``ADMISSION_TIMEOUT`` if the timeout elapsed
        before a slot was acquired (semaphore NOT held).

        Args:
            request: The media request (used for per-chat limiter key).

        Returns:
            ``None`` on success (caller must release semaphore), or
            ``ADMISSION_TIMEOUT`` on timeout (semaphore not held).
        """
        assert self._semaphore is not None, "_admit: _semaphore is None"
        acquired = False
        try:
            async with asyncio.timeout(self._admissionTimeoutSeconds):
                # Rate limiters (sliding-window, no explicit release needed).
                if self._chatLimiterQueue is not None:
                    chatKey = str(request.chatId)
                    await RateLimiterManager.getInstance().applyLimit(self._chatLimiterQueue, key=chatKey)
                if self._globalLimiterQueue is not None:
                    await RateLimiterManager.getInstance().applyLimit(self._globalLimiterQueue)
                # Concurrency semaphore.
                await self._semaphore.acquire()
                acquired = True
        except asyncio.TimeoutError:
            if acquired:
                self._semaphore.release()
            logger.warning("transcribeMedia: admission timeout for %s", request.mediaId)
            return STTErrorCode.ADMISSION_TIMEOUT
        return None

    async def _downloadAndBound(self, request: STTMediaRequest) -> Tuple[Optional[bytes], Optional[STTErrorCode]]:
        """Download media bytes via the loader and verify size bounds.

        Calls ``request.loader(self._maxSourceBytes)`` and checks:
        - ``None`` return → ``SOURCE_SIZE_UNKNOWN``.
        - Loader raises → ``DOWNLOAD_ERROR``.
        - ``len(data) > maxSourceBytes`` → ``SOURCE_TOO_LARGE``.

        Args:
            request: The media request containing the loader callable.

        Returns:
            A tuple ``(data, None)`` on success, or ``(None, errorCode)``
            on failure.
        """
        try:
            data: Optional[bytes] = await request.loader(self._maxSourceBytes)
        except Exception:  # noqa: BLE001 — loader failure
            logger.warning("transcribeMedia: download error for %s", request.mediaId, exc_info=True)
            return None, STTErrorCode.DOWNLOAD_ERROR

        if data is None:
            logger.warning("transcribeMedia: loader returned None (size unknown) for %s", request.mediaId)
            return None, STTErrorCode.SOURCE_SIZE_UNKNOWN

        if len(data) > self._maxSourceBytes:
            logger.warning(
                "transcribeMedia: downloaded %d bytes > max %d for %s",
                len(data),
                self._maxSourceBytes,
                request.mediaId,
            )
            return None, STTErrorCode.SOURCE_TOO_LARGE

        return data, None

    def _mapOutcome(self, result: TranscriptionResult) -> STTOutcome:
        """Map a ``TranscriptionResult`` to an ``STTOutcome``.

        ``ERROR`` → ``FAILED`` with the provider's error code.
        ``FINAL`` / ``NO_SPEECH`` → ``DONE`` with the formatted transcript.
        The formatter returns ``[No speech detected]`` for empty segments
        (NO_SPEECH) automatically, so no special-casing is needed.

        Args:
            result: The provider's transcription result.

        Returns:
            STTOutcome: ``DONE`` with the formatted transcript, or ``FAILED``
            with the provider's error code.
        """
        if result.status == STTResultStatus.ERROR:
            return STTOutcome(status=MediaStatus.FAILED, description=None, errorCode=result.errorCode)
        description = formatTranscript(result, self._maxTranscriptChars)
        return STTOutcome(status=MediaStatus.DONE, description=description)

    async def _persistTerminal(self, mediaId: str, outcome: STTOutcome, *, maxRetries: Optional[int] = None) -> None:
        """Persist a terminal status via verified compare-and-set.

        Attempts ``setStatusVerified(mediaId, expected=PENDING, target=<outcome.status>)``
        up to ``maxRetries`` times with short backoff.  On exhaustion, logs
        CRITICAL.  Never raises.

        Args:
            mediaId: The file_unique_id to terminalize.
            outcome: The outcome whose ``status`` and ``description`` are
                persisted.
            maxRetries: Override for retry count; defaults to class constant.

        Returns:
            None.
        """
        if maxRetries is None:
            maxRetries = self._PERSIST_TERMINAL_MAX_RETRIES
        assert self._database is not None, "_persistTerminal: _database is None"
        repo = self._database.mediaAttachments
        for attempt in range(1, maxRetries + 1):
            result = await repo.setStatusVerified(
                mediaId, expected=MediaStatus.PENDING, target=outcome.status, description=outcome.description
            )
            if result is not None:
                return
            logger.warning(
                "transcribeMedia: persist %s attempt %d/%d failed (row no longer PENDING) for %s",
                outcome.status,
                attempt,
                maxRetries,
                mediaId,
            )
            if attempt < maxRetries:
                await asyncio.sleep(self._PERSIST_TERMINAL_BACKOFF)
        logger.critical(
            "transcribeMedia: %s persist exhausted %d retries for %s — row stays PENDING for reclaim",
            outcome.status,
            maxRetries,
            mediaId,
        )
