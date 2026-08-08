"""Yandex SpeechKit v3 async STT provider (raw httpx wire lifecycle).

This module implements :class:`YandexSpeechKitProvider`, the one concrete
:class:`~lib.stt.abstract.AbstractSTTProvider` for ``lib/stt``. It owns a single
persistent :class:`httpx.AsyncClient` (configured with the injected, already-resolved
:class:`~lib.proxy.ProxyConfig`) and drives the Yandex SpeechKit v3 deferred-recognition
lifecycle end to end: submit → poll → getRecognition → delete.

Per ``docs/design/lib-stt-v1.md`` §7 (the authoritative wire spec) and §1 (the dependency
firewall):

- **Proxy is injected** (dependency-firewall seam #1). The provider receives an
  already-resolved :class:`~lib.proxy.ProxyConfig` and spreads
  ``proxyConfig.toKwargs()`` into its ``httpx.AsyncClient`` — it never resolves the
  proxy from config/services itself (that bypasses per-service proxy lifecycle
  registration, parent §9). The exact pattern mirrors
  :mod:`lib.yandex_search.client` and :mod:`lib.openweathermap.client`.
- **Raw httpx, not the SDK** (§7.5 / D6): explicit wire, streaming-cap, proxy, retry,
  and cleanup control. No ``yandex-cloud-ml-sdk``.
- **Never raise for expected failures** (load-bearing contract #2, §4/§7.4):
  :meth:`YandexSpeechKitProvider.transcribe` returns a
  :class:`~lib.stt.models.TranscriptionResult` with ``status=ERROR`` for every
  expected provider/transport/protocol failure — it never raises. The constructor MAY
  raise on startup configuration validation (the only permitted raise site).

Authoritative references:
- §7.1 (authentication + submit URL/body/headers), §7.2 (operation lifecycle),
  §7.3 (event parsing — delegated to :mod:`lib.stt.providers.yandex_events`),
  §7.4 (retry policy) of ``docs/design/lib-stt-v1.md``.
- [async v3 guide](https://aistudio.yandex.ru/docs/en/speechkit/stt/api/transcribation-api-v3.html),
  [v3 service proto](https://github.com/yandex-cloud/cloudapi/blob/master/yandex/cloud/ai/stt/v3/stt_service.proto),
  [SpeechKit limits](https://aistudio.yandex.ru/docs/en/speechkit/concepts/limits).
"""

import asyncio
import base64
import logging
from collections.abc import Sequence
from typing import Dict, Optional, Tuple

import httpx

from lib.proxy import ProxyConfig, ProxyKwargs
from lib.stats import StatsStorage

from ..abstract import AbstractSTTProvider
from ..models import (
    AudioFormatSpec,
    ExtractedAudio,
    STTAudioContainerType,
    STTErrorCode,
    STTResultStatus,
    TranscriptionResult,
)
from .yandex_events import DEFAULT_MAX_RESULT_BYTES, parseRecognitionEvents
from .yandex_object_storage import YandexObjectStorage

logger = logging.getLogger(__name__)
"""Module logger (mirrors :mod:`lib.yandex_search.client` — no logger injection)."""

#: Ordered accepted input formats (§7). OGG_OPUS is FIRST because it is the preferred
#: transcode target for speech efficiency (the audio module's negotiation picks the
#: first supported compressed format). OGG_OPUS/MP3 are documented as restriction-free;
#: WAV is bounded conservatively. The exact multi-channel ceiling is unpublished and is
#: indirectly bounded by the decoded-buffer cap (§5), so a generous value is used here.
_SUPPORTED_INPUT_FORMATS: Tuple[AudioFormatSpec, ...] = (
    AudioFormatSpec(
        container=STTAudioContainerType.OGG_OPUS,
        minChannels=1,
        maxChannels=8,
        minSampleRate=8000,
        maxSampleRate=48000,
    ),
    AudioFormatSpec(
        container=STTAudioContainerType.MP3,
        minChannels=1,
        maxChannels=2,
        minSampleRate=8000,
        maxSampleRate=48000,
    ),
    AudioFormatSpec(
        container=STTAudioContainerType.WAV,
        minChannels=1,
        maxChannels=2,
        minSampleRate=8000,
        maxSampleRate=48000,
    ),
)


class _ProviderFailure(Exception):
    """Internal sentinel exception carrying an :class:`STTErrorCode`.

    Used ONLY inside the provider's private lifecycle helpers to signal an expected
    failure to the never-raise boundary in :meth:`YandexSpeechKitProvider.transcribe`,
    which catches it and maps it to ``TranscriptionResult(status=ERROR)``. It never
    escapes the module (load-bearing contract #2). ``asyncio`` timeout and unexpected
    exceptions are handled separately by the boundary.

    Attributes:
        errorCode: The provider-neutral failure category to surface.
    """

    __slots__ = ("errorCode",)

    def __init__(self, errorCode: STTErrorCode, message: str = "") -> None:
        """Initialize the sentinel with an error code and optional message.

        Args:
            errorCode: The provider-neutral failure category to surface.
            message: Optional human-readable detail (logged only, never surfaced to the
                transcript; must not contain credentials/base64).

        Returns:
            None
        """
        self.errorCode = errorCode
        super().__init__(message)


class YandexSpeechKitProvider(AbstractSTTProvider):
    """Yandex SpeechKit v3 deferred-recognition async STT provider.

    Owns one persistent :class:`httpx.AsyncClient` (built at construction with the
    injected ``ProxyConfig`` spread via ``toKwargs()``) and drives the full
    submit→poll→fetch→delete lifecycle in :meth:`transcribe`. Caps (operation/request
    timeouts, poll delays, result-byte cap, retry budget) and config (credentials,
    model, language, proxy) are supplied at construction — :meth:`transcribe` takes only
    the format-aware :class:`~lib.stt.models.ExtractedAudio`.

    The raise/return contract (load-bearing contract #2, §4): :meth:`transcribe`
    returns a :class:`~lib.stt.models.TranscriptionResult` for **every** expected
    outcome, including failures — it never raises. The constructor MAY raise
    :class:`ValueError` on startup configuration validation (missing credentials,
    non-positive limits).

    Attributes:
        _httpClient: The persistent httpx client (proxy-configured at construction).
        proxyConfig: The injected, already-resolved ProxyConfig (or None).
    """

    # --- Wire endpoints (§7.1 / §7.2) ---------------------------------------
    _SUBMIT_URL: str = "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync"
    _OPERATIONS_BASE_URL: str = "https://operation.api.cloud.yandex.net/operations"
    _GET_RECOGNITION_URL: str = "https://stt.api.cloud.yandex.net/stt/v3/getRecognition"
    _DELETE_RECOGNITION_URL: str = "https://stt.api.cloud.yandex.net/stt/v3/deleteRecognition"

    # Slots for every instance attribute set in __init__ (below); the base-class
    # slots already cover proxyConfig/statsStorage/_extraLabels, so a __dict__ is
    # never created for provider instances.
    __slots__ = (
        "_maxInlineBytes",
        "_objectStorage",
        "_apiKey",
        "_folderId",
        "_model",
        "_language",
        "_operationBudgetSeconds",
        "_pollIntervalSeconds",
        "_maxPollIntervalSeconds",
        "_maxPolls",
        "_maxRetries",
        "_retryBackoffSeconds",
        "_maxResultBytes",
        "_authHeaders",
        "_httpClient",
    )

    def __init__(
        self,
        *,
        apiKey: str,
        folderId: str,
        model: str = "general",
        language: str = "ru-RU",
        requestTimeoutSeconds: float = 30.0,
        operationBudgetSeconds: float = 180.0,
        pollIntervalSeconds: float = 2.0,
        maxPollIntervalSeconds: float = 10.0,
        maxPolls: int = 100,
        maxRetries: int = 3,
        retryBackoffSeconds: float = 1.0,
        maxResultBytes: int = DEFAULT_MAX_RESULT_BYTES,
        maxInlineBytes: int = 41943040,
        objectStorageBucket: Optional[str] = None,
        objectStoragePrefix: str = "stt/",
        objectStorageKeyId: Optional[str] = None,
        objectStorageKeySecret: Optional[str] = None,
        proxyConfig: Optional[ProxyConfig] = None,
        statsStorage: Optional[StatsStorage] = None,
        **extraKwargs,
    ) -> None:
        """Initialize the provider, validating startup config and building the client.

        Caps and config are received here (not on :meth:`transcribe`) per the
        :class:`~lib.stt.abstract.AbstractSTTProvider` contract. This is the ONLY place
        the provider may raise (startup config validation, load-bearing contract #2).

        Args:
            apiKey: Yandex Cloud API key (``Authorization: Api-Key <apiKey>``). Required.
            folderId: Yandex Cloud folder ID (``x-folder-id`` header). Required.
            model: Recognition model name (``recognition_model.model``). Defaults to
                ``"general"``.
            language: Single BCP-47 language code for the WHITELIST restriction.
                Defaults to ``"ru-RU"``.
            proxyConfig: Already-resolved :class:`~lib.proxy.ProxyConfig` (the
                dependency-firewall seam — resolved in the service layer via
                ``ProxyService.resolveProxy``), or ``None`` for no proxy. Spread into
                the ``httpx.AsyncClient`` via ``toKwargs()``.
            requestTimeoutSeconds: Per-httpx-request timeout in seconds (§8.1: 30 s).
            operationBudgetSeconds: Wall-clock operation budget in seconds across
                submit + poll + fetch (§7.2/§7.4: 180 s — constructor default; the
                shipped ``stt.toml`` config overrides to 2400). Best-effort deletion
                runs outside this budget.
            pollIntervalSeconds: Initial poll interval in seconds (§8.1: 2 s).
            maxPollIntervalSeconds: Ceiling for the exponential poll backoff in seconds
                (§8.1: 10 s).
            maxPolls: Hard cap on the number of poll iterations (a safety valve so a
                pathological never-done operation cannot loop indefinitely even if the
                wall-clock budget is generous). Exhaustion yields PROVIDER_ERROR.
            maxRetries: Maximum retries for idempotent GET (poll/fetch) on transient
                transport errors / 429 / 5xx (§7.4). Submit is NEVER retried.
            retryBackoffSeconds: Base for the exponential GET-retry backoff in seconds.
                Honours ``Retry-After`` when the server provides it.
            maxResultBytes: Result-body byte cap forwarded to
                :func:`~lib.stt.providers.yandex_events.parseRecognitionEvents` (§8.1:
                5 MiB default).
            maxInlineBytes: Routing threshold in bytes measured on ``len(audio.data)``.
                Clips below this go inline; at/above this route to Object Storage (when
                configured). Default 40 MiB (41943040). Must be positive.
            objectStorageBucket: Yandex Object Storage bucket name for large-clip routing.
                When set (non-empty), Object Storage is enabled and both
                ``objectStorageKeyId`` and ``objectStorageKeySecret`` are required. When
                ``None`` or empty, the provider is inline-only.
            objectStoragePrefix: Key prefix for uploaded objects (default ``"stt/"``).
            objectStorageKeyId: Yandex static access-key ID for Object Storage (SigV4).
                Required when ``objectStorageBucket`` is set.
            objectStorageKeySecret: Yandex static access-key secret for Object Storage
                (SigV4). Required when ``objectStorageBucket`` is set.
            statsStorage: Optional :class:`~lib.stats.stats_storage.StatsStorage` for
                recording per-transcription statistics. When ``None`` (default), a
                :class:`~lib.stats.stats_storage.NullStatsStorage` no-op is used.
                Mirrors the ``lib/ai`` injection pattern (design §5.2).

        Raises:
            ValueError: If required credentials are missing/empty, any required string
                parameter contains an unresolved ``${…}`` placeholder (indicating a
                missing environment variable), any numeric limit is non-positive,
                ``maxPollIntervalSeconds < pollIntervalSeconds``, ``maxInlineBytes`` is
                not positive, or Object Storage params are partially configured (bucket
                without both keys, or keys without bucket). Startup validation,
                load-bearing contract #2.

        Returns:
            None
        """

        super().__init__(proxyConfig=proxyConfig, statsStorage=statsStorage)

        if not apiKey or not isinstance(apiKey, str):
            raise ValueError("apiKey must be a non-empty string")
        if not folderId or not isinstance(folderId, str):
            raise ValueError("folderId must be a non-empty string")
        if not model or not isinstance(model, str):
            raise ValueError("model must be a non-empty string")
        if not language or not isinstance(language, str):
            raise ValueError("language must be a non-empty string")

        for name, value in (("apiKey", apiKey), ("folderId", folderId), ("model", model), ("language", language)):
            if value.startswith("${") and value.endswith("}"):
                raise ValueError(f"{name} contains an unresolved placeholder: {value!r}")

        if requestTimeoutSeconds <= 0:
            raise ValueError("requestTimeoutSeconds must be positive")
        if operationBudgetSeconds <= 0:
            raise ValueError("operationBudgetSeconds must be positive")
        if pollIntervalSeconds < 0:
            raise ValueError("pollIntervalSeconds must be non-negative")
        if maxPollIntervalSeconds < pollIntervalSeconds:
            raise ValueError("maxPollIntervalSeconds must be >= pollIntervalSeconds")
        if maxPolls <= 0:
            raise ValueError("maxPolls must be positive")
        if maxRetries < 0:
            raise ValueError("maxRetries must be non-negative")
        if retryBackoffSeconds < 0:
            raise ValueError("retryBackoffSeconds must be non-negative")
        if maxResultBytes <= 0:
            raise ValueError("maxResultBytes must be positive")

        # --- Phase 2: Object Storage validation (design §6.3) ---
        if maxInlineBytes <= 0:
            raise ValueError("maxInlineBytes must be positive")

        osBucket: Optional[str] = objectStorageBucket if objectStorageBucket else None
        osKeyId: Optional[str] = objectStorageKeyId if objectStorageKeyId else None
        osKeySecret: Optional[str] = objectStorageKeySecret if objectStorageKeySecret else None

        # All-or-nothing: if any OS cred is present, bucket must also be present.
        if osBucket is None and (osKeyId is not None or osKeySecret is not None):
            raise ValueError("objectStorageKeyId/objectStorageKeySecret set without objectStorageBucket")
        # If bucket is present, both keys are required.
        if osBucket is not None and (osKeyId is None or osKeySecret is None):
            raise ValueError("objectStorageBucket set but objectStorageKeyId or objectStorageKeySecret missing")
        # Unresolved placeholders in OS creds (same rule as api-key/folder-id).
        for name, value in (
            ("objectStorageBucket", objectStorageBucket),
            ("objectStorageKeyId", objectStorageKeyId),
            ("objectStorageKeySecret", objectStorageKeySecret),
        ):
            if value and isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                raise ValueError(f"{name} contains an unresolved placeholder: {value!r}")

        # Store maxInlineBytes and construct the Object Storage helper when configured.
        self._maxInlineBytes: int = maxInlineBytes
        if osBucket is not None:
            self._objectStorage: Optional[YandexObjectStorage] = YandexObjectStorage(
                bucket=osBucket,
                prefix=objectStoragePrefix,
                keyId=osKeyId,  # type: ignore[arg-type]
                keySecret=osKeySecret,  # type: ignore[arg-type]
            )
        else:
            self._objectStorage = None

        self._apiKey: str = apiKey
        self._folderId: str = folderId
        self._model: str = model
        self._language: Sequence[str] = [language]
        self._operationBudgetSeconds: float = operationBudgetSeconds
        self._pollIntervalSeconds: float = pollIntervalSeconds
        self._maxPollIntervalSeconds: float = maxPollIntervalSeconds
        self._maxPolls: int = maxPolls
        self._maxRetries: int = maxRetries
        self._retryBackoffSeconds: float = retryBackoffSeconds
        self._maxResultBytes: int = maxResultBytes

        self._authHeaders: Dict[str, str] = {
            "Authorization": f"Api-Key {apiKey}",
            "x-folder-id": folderId,
        }

        self._extraLabels["model"] = model

        # Dependency-firewall seam #1 (§1/§7.2): spread the already-resolved proxy
        # config into the persistent client exactly like lib.yandex_search.client and
        # lib.openweathermap.client. When proxyConfig is None, no proxy kwargs spread.
        # Typed as ProxyKwargs (a total=False TypedDict) so spreading into the httpx
        # client is type-checked the same way lib.yandex_search.client does it.
        proxyKwargs: ProxyKwargs = self.proxyConfig.toKwargs() if self.proxyConfig is not None else ProxyKwargs()
        self._httpClient: httpx.AsyncClient = httpx.AsyncClient(
            **proxyKwargs,
            timeout=httpx.Timeout(requestTimeoutSeconds),
        )

    def supportedInputFormats(self) -> Sequence[AudioFormatSpec]:
        """Ordered accepted input containers, OGG_OPUS first (preferred transcode target).

        Consumed by ``audio.py`` for pass-through/transcode negotiation. The FIRST entry
        is the preferred transcode target (OGG_OPUS for speech efficiency). Does NOT
        describe recognition quality (quality-by-format is UNVERIFIED, §10(b)).

        Returns:
            Sequence[AudioFormatSpec]: ``(OGG_OPUS, MP3, WAV)``.
        """
        return _SUPPORTED_INPUT_FORMATS

    async def _transcribe(self, audio: ExtractedAudio) -> TranscriptionResult:
        """Transcribe format-aware ExtractedAudio through the full Yandex v3 lifecycle.

        For clips below ``maxInlineBytes`` the lifecycle is byte-for-byte identical
        to v1: submit (inline ``content``) → poll → getRecognition → parse →
        best-effort deleteRecognition.

        For clips at/above ``maxInlineBytes`` the Object-Storage path (design §4.3)
        is followed: **staging upload** (outside the operation budget) → submit
        (via ``uri``) → poll → getRecognition → parse, then **best-effort cleanup**
        of both the SpeechKit operation and the staged object in ``finally``.

        Upload is **outside** the ``asyncio.timeout`` budget (the budget covers
        submit + poll + fetch only, §7.4).  The upload is bounded by the Object
        Storage helper's own transport timeouts (design §3.1).

        **Never raises** (load-bearing contract #2): every expected failure returns
        ``TranscriptionResult(status=ERROR, errorCode=...)``.  A genuinely unexpected
        exception is also caught and mapped to PROVIDER_ERROR.  ``asyncio.CancelledError``
        propagates (``except Exception`` does not catch ``BaseException``).

        This method does **not** record statistics itself — the base ``transcribe``
        records stats for every outcome (FINAL, NO_SPEECH, and all ERROR variants)
        via ``_recordStats``, best-effort and never raising (design §5.3).

        Args:
            audio: The format-aware audio after negotiation. ``audio.container`` drives
                the ``container_audio.container_audio_type`` field dynamically.

        Returns:
            TranscriptionResult: FINAL/NO_SPEECH from the parsed recognition result, or
            ERROR (PROVIDER_ERROR for transport/timeout/operation errors; PROTOCOL_ERROR
            surfaced from the parser for malformed result bodies; SOURCE_TOO_LARGE when
            the extracted payload exceeds the inline threshold and Object Storage is
            disabled; OBJECT_STORAGE_ERROR when the Object Storage upload fails).
        """
        objectUri: Optional[str] = None

        # --- Staging: OUTSIDE the operation budget (design §4.3) ---
        # Upload is prep, not a SpeechKit operation step.  Bounded by the
        # helper's own transport timeouts, not operationBudgetSeconds.
        if len(audio.data) >= self._maxInlineBytes:
            if self._objectStorage is None:
                # §4.2: over-threshold + OS disabled → SOURCE_TOO_LARGE.
                return self._errorResult(STTErrorCode.SOURCE_TOO_LARGE)
            try:
                objectUri = await self._objectStorage.upload(audio.data)
            except Exception:  # noqa: BLE001 — upload failure → OBJECT_STORAGE_ERROR
                logger.exception("Yandex STT Object Storage upload failed")
                return self._errorResult(STTErrorCode.OBJECT_STORAGE_ERROR)

        # --- SpeechKit operation: INSIDE the operation budget ---
        operationId: Optional[str] = None
        operationFailed = False
        result: TranscriptionResult  # assigned in every branch below
        recognitionBytes: bytes = b""  # assigned only on operation success
        try:
            # §7.4: the operation budget "starts immediately before submit
            # and includes submit, polling, and the successful result fetch".
            async with asyncio.timeout(self._operationBudgetSeconds):
                operationId = await self._submit(audio, objectUri=objectUri)
                recognitionBytes = await self._pollAndFetch(operationId)
        except _ProviderFailure as failure:
            logger.warning("Yandex STT transcribe failed (%s): %s", failure.errorCode, failure)
            result = self._errorResult(failure.errorCode)
            operationFailed = True
        except TimeoutError:
            logger.warning(
                "Yandex STT operation budget (%ss) exhausted; operationId=%s",
                self._operationBudgetSeconds,
                operationId,
            )
            result = self._errorResult(STTErrorCode.PROVIDER_ERROR)
            operationFailed = True
        except Exception:  # noqa: BLE001 — the never-raise boundary (contract #2)
            logger.exception("Yandex STT unexpected transcribe failure; operationId=%s", operationId)
            result = self._errorResult(STTErrorCode.PROVIDER_ERROR)
            operationFailed = True
        finally:
            # Best-effort cleanup runs whenever an operation was created, regardless
            # of outcome.  It is OUTSIDE the operation budget and never raises.
            if operationId is not None:
                await self._bestEffortDelete(operationId)
            # §4.3: best-effort object delete after operation delete.
            # Must not invalidate a successful transcript (never raises).
            if objectUri is not None:
                await self._bestEffortDeleteObject(objectUri)

        # Parse stays OUTSIDE the operation budget (it is fast, in-memory, and §7.4
        # lists only submit/poll/fetch as budgeted) but INSIDE the never-raise
        # boundary — an unexpected parse failure (e.g. a deeply-nested JSON body that
        # trips CPython's recursion limit, or any other exception not in the parser's
        # caught tuple) is mapped to PROTOCOL_ERROR rather than escaping transcribe
        # (load-bearing contract #2).
        # If the operation already failed, skip parsing.
        if not operationFailed:
            try:
                result = parseRecognitionEvents(recognitionBytes, self._maxResultBytes)
            except Exception:  # noqa: BLE001 — defense-in-depth for the parse path too
                logger.exception("Yandex STT unexpected parse failure; operationId=%s", operationId)
                result = self._errorResult(STTErrorCode.PROTOCOL_ERROR)
        if not operationFailed and result.status is STTResultStatus.ERROR:
            logger.warning("Yandex STT recognition parse failed: %s", result.errorCode)

        return result

    async def aclose(self) -> None:
        """Close the persistent httpx client (graceful shutdown).

        Called by the service layer (the future STTService) during graceful shutdown,
        after in-flight STT workers have drained (parent §11.3). Safe to call multiple
        times (httpx ``aclose`` is
        idempotent). Calling :meth:`transcribe` after ``aclose`` returns an ERROR result
        rather than raising (the never-raise boundary maps the closed-client
        ``RuntimeError`` to PROVIDER_ERROR).

        Returns:
            None
        """
        await self._httpClient.aclose()
        if self._objectStorage is not None:
            await self._objectStorage.aclose()

    # ------------------------------------------------------------------ #
    # Private lifecycle helpers
    # ------------------------------------------------------------------ #

    async def _submit(self, audio: ExtractedAudio, *, objectUri: Optional[str] = None) -> str:
        """Submit the audio for deferred recognition (§7.1). NEVER retried (§7.4).

        Builds the protobuf-JSON body with ``container_audio.container_audio_type`` set
        dynamically from ``audio.container`` (the wire label).  On the inline path the
        audio bytes are base64-encoded as ``content``; on the Object-Storage path
        ``objectUri`` is used as the ``uri`` field (design §4.4).  POSTs to
        ``recognizeFileAsync`` with the auth headers.

        Args:
            audio: The format-aware audio after negotiation.
            objectUri: When not None, submit via the ``uri`` field instead of
                inline ``content`` (design §4.4).

        Returns:
            str: The Yandex operation ID parsed from the submit response.

        Raises:
            _ProviderFailure: PROVIDER_ERROR on a non-2xx response, transport error,
                unparseable JSON, or a response missing the operation ID.
        """
        body: Dict[str, object] = self._buildSubmitBody(audio, objectUri=objectUri)
        headers: Dict[str, str] = {**self._authHeaders, "Content-Type": "application/json"}
        try:
            response = await self._httpClient.post(self._SUBMIT_URL, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise _ProviderFailure(STTErrorCode.PROVIDER_ERROR, f"submit transport error: {exc}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            # §7.4: NEVER retry the submit POST (a timeout can occur after Yandex has
            # accepted a billable operation; retrying can create duplicate cost).
            raise _ProviderFailure(
                STTErrorCode.PROVIDER_ERROR,
                f"submit non-2xx status {response.status_code}",
            )
        try:
            payload: object = response.json()
        except ValueError as exc:  # json.JSONDecodeError subclasses ValueError
            raise _ProviderFailure(STTErrorCode.PROVIDER_ERROR, f"submit bad JSON: {exc}") from exc
        operationId: object = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(operationId, str) or not operationId:
            raise _ProviderFailure(STTErrorCode.PROVIDER_ERROR, "submit response missing operation id")
        return operationId

    def _buildSubmitBody(self, audio: ExtractedAudio, *, objectUri: Optional[str] = None) -> Dict[str, object]:
        """Build the protobuf-JSON recognizeFileAsync body (§7.1 / design §4.4).

        The ``recognition_model`` block (model, ``container_audio``, language
        restriction, text normalization) is **identical** for both paths.  Only
        the top-level input field differs: ``content`` (base64-encoded audio)
        for the inline path, or ``uri`` (an Object Storage URI) for the
        Object-Storage path.  When ``objectUri`` is not None the audio bytes
        are NOT base64-encoded.

        Args:
            audio: The format-aware audio after negotiation.
            objectUri: When not None, use the Object Storage ``uri`` field
                instead of the inline ``content`` field (design §4.4).

        Returns:
            Dict[str, object]: The protobuf-JSON submit body.
        """
        recognitionModel: Dict[str, object] = {
            "model": self._model,
            "audio_format": {
                "container_audio": {"container_audio_type": audio.container.toYandexSpeechKit()},
            },
            "language_restriction": {
                "restriction_type": "WHITELIST",
                "language_code": self._language,
            },
            "text_normalization": {"literature_text": True},
        }
        if objectUri is not None:
            return {"uri": objectUri, "recognition_model": recognitionModel}
        encodedContent: str = base64.b64encode(audio.data).decode("ascii")
        return {"content": encodedContent, "recognition_model": recognitionModel}

    async def _pollAndFetch(self, operationId: str) -> bytes:
        """Poll the operation until done, then fetch the recognition bytes (§7.2).

        Polls ``GET operations/{id}`` up to ``maxPolls`` times (sleeping with exponential
        backoff between non-done polls). When ``done=true`` with an ``error`` → PROVIDER_ERROR.
        When ``done=true`` without error → fetches the recognition result bytes.

        Args:
            operationId: The Yandex operation ID.

        Returns:
            bytes: The raw ``getRecognition`` response body (provisional streaming-JSON).

        Raises:
            _ProviderFailure: PROVIDER_ERROR when the operation reports an error or
                ``maxPolls`` is exhausted; PROTOCOL_ERROR on a malformed poll response.
        """
        for attempt in range(self._maxPolls):
            operation = await self._pollOnce(operationId)
            if self._isDone(operation):
                if self._hasError(operation):
                    raise _ProviderFailure(
                        STTErrorCode.PROVIDER_ERROR,
                        f"operation {operationId} reported error: {operation.get('error')!r}",
                    )
                return await self._fetchRecognition(operationId)
            # Sleep between polls (not after the last one — it raises below if still not done).
            if attempt < self._maxPolls - 1:
                await asyncio.sleep(self._pollDelay(attempt))
        raise _ProviderFailure(
            STTErrorCode.PROVIDER_ERROR,
            f"maxPolls ({self._maxPolls}) exhausted before operation {operationId} completed",
        )

    async def _pollOnce(self, operationId: str) -> Dict[str, object]:
        """Fetch one operation state (§7.2). Retries transient 429/5xx (§7.4).

        Args:
            operationId: The Yandex operation ID.

        Returns:
            Dict[str, object]: The parsed operation JSON object.

        Raises:
            _ProviderFailure: PROVIDER_ERROR on exhausted transport/429/5xx retries or a
                4xx client error; PROTOCOL_ERROR on a non-object / unparseable response.
        """
        url = f"{self._OPERATIONS_BASE_URL}/{operationId}"
        response = await self._getWithRetry(url)
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise _ProviderFailure(STTErrorCode.PROTOCOL_ERROR, f"poll bad JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise _ProviderFailure(STTErrorCode.PROTOCOL_ERROR, "poll response is not a JSON object")
        return payload

    async def _fetchRecognition(self, operationId: str) -> bytes:
        """Fetch the recognition result body (§7.2). Retries transient 429/5xx (§7.4).

        Each fetch is atomic (§7.4): the full body is buffered here and parsed
        independently by :func:`parseRecognitionEvents`; no partial segments are
        committed from a failed stream.

        Args:
            operationId: The Yandex operation ID.

        Returns:
            bytes: The raw recognition response body (provisional streaming-JSON).

        Raises:
            _ProviderFailure: PROVIDER_ERROR on exhausted transport/429/5xx retries or a
                4xx client error.
        """
        response = await self._getWithRetry(
            self._GET_RECOGNITION_URL,
            params={"operation_id": operationId},
        )
        return response.content

    async def _getWithRetry(
        self,
        url: str,
        *,
        params: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """Perform an idempotent GET with bounded retry on transient errors (§7.4).

        Retries transport errors, 429, and 5xx up to ``maxRetries`` times with
        exponential backoff (honouring ``Retry-After``). Authentication/validation 4xx
        responses are NOT retried. The overall operation budget bounds the aggregate.

        Args:
            url: The full request URL.
            params: Optional query parameters.

        Returns:
            httpx.Response: The successful (2xx) response.

        Raises:
            _ProviderFailure: PROVIDER_ERROR when retries are exhausted or a non-retried
                4xx occurs.
        """
        lastStatus: Optional[int] = None
        for attempt in range(self._maxRetries + 1):
            try:
                response = await self._httpClient.get(url, headers=self._authHeaders, params=params)
            except httpx.HTTPError as exc:
                if attempt < self._maxRetries:
                    await asyncio.sleep(self._retryDelay(attempt, response=None))
                    continue
                raise _ProviderFailure(STTErrorCode.PROVIDER_ERROR, f"GET {url} transport error: {exc}") from exc
            if response.status_code == 429 or response.status_code >= 500:
                lastStatus = response.status_code
                if attempt < self._maxRetries:
                    await asyncio.sleep(self._retryDelay(attempt, response=response))
                    continue
                raise _ProviderFailure(
                    STTErrorCode.PROVIDER_ERROR,
                    f"GET {url} exhausted retries: last status {lastStatus}",
                )
            if response.status_code >= 400:
                # §7.4: do not retry authentication/validation 4xx responses.
                raise _ProviderFailure(
                    STTErrorCode.PROVIDER_ERROR,
                    f"GET {url} non-retried client error: {response.status_code}",
                )
            return response
        # Unreachable: the loop always returns or raises within maxRetries+1 iterations.
        raise _ProviderFailure(STTErrorCode.PROVIDER_ERROR, f"GET {url} retry loop exited unexpectedly")

    async def _bestEffortDelete(self, operationId: str) -> None:
        """Best-effort deleteRecognition to reduce server-side retention (§7.2/§7.4).

        Single attempt, never retried, never raises. A failure logs a warning but does
        NOT turn a successful transcription into ERROR (this runs in the ``finally``
        block after the result is already determined where applicable).

        Args:
            operationId: The Yandex operation ID.

        Returns:
            None
        """
        try:
            await self._httpClient.delete(
                self._DELETE_RECOGNITION_URL,
                headers=self._authHeaders,
                params={"operation_id": operationId},
            )
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup must never raise
            logger.warning("Yandex STT best-effort delete failed for operation %s: %s", operationId, exc)

    async def _bestEffortDeleteObject(self, objectUri: str) -> None:
        """Best-effort delete of a staged Object Storage object (design §4.3).

        Runs in the ``finally`` block after the operation delete.  Single
        attempt, never retried, never raises — a failure logs a warning but
        does NOT invalidate a successful transcript.  ``except Exception``
        (not ``BaseException``) ensures ``asyncio.CancelledError`` propagates.

        Args:
            objectUri: The URI previously returned by ``_objectStorage.upload()``.

        Returns:
            None
        """
        assert self._objectStorage is not None  # guarded by caller
        try:
            await self._objectStorage.delete(objectUri)
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup must never raise
            logger.warning("Yandex STT best-effort object delete failed for %s: %s", objectUri, exc)

    # ------------------------------------------------------------------ #
    # Private timing / parsing helpers
    # ------------------------------------------------------------------ #

    def _pollDelay(self, attempt: int) -> float:
        """Exponential poll backoff, capped at ``maxPollIntervalSeconds`` (§8.1).

        The exponent is capped at 100 so ``2 ** attempt`` stays within ``float``
        range even for a pathological attempt index (``2 ** 1024`` overflows).

        Args:
            attempt: The zero-based poll attempt index.

        Returns:
            float: The delay in seconds before the next poll.
        """
        return min(self._pollIntervalSeconds * (2 ** min(attempt, 100)), self._maxPollIntervalSeconds)

    def _retryDelay(self, attempt: int, *, response: Optional[httpx.Response]) -> float:
        """GET-retry delay honouring ``Retry-After`` when present (§7.4).

        The exponential-backoff cap reuses ``_maxPollIntervalSeconds`` (spec-consistent:
        both poll and GET-retry backoffs share the same wall-clock ceiling), NOT
        ``retryBackoffSeconds`` — the latter is only the backoff base, not the cap.

        Args:
            attempt: The zero-based retry attempt index.
            response: The response carrying a possible ``Retry-After`` header (None for
                transport errors).

        Returns:
            float: The delay in seconds before the next retry.
        """
        retryAfter = self._retryAfterSeconds(response)
        if retryAfter is not None:
            return retryAfter
        return min(self._retryBackoffSeconds * (2 ** min(attempt, 100)), self._maxPollIntervalSeconds)

    @staticmethod
    def _retryAfterSeconds(response: Optional[httpx.Response]) -> Optional[float]:
        """Parse a ``Retry-After`` delta-seconds header, if present and valid.

        Args:
            response: The response to read the header from, or None.

        Returns:
            Optional[float]: The non-negative delay in seconds, or None when the header
            is absent or unparseable (HTTP-date form is not supported in v1).
        """
        if response is None:
            return None
        header = response.headers.get("Retry-After")
        if not header:
            return None
        try:
            return max(0.0, float(header))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _isDone(operation: Dict[str, object]) -> bool:
        """Whether the operation JSON reports ``done=true``.

        Uses identity (``is True``) rather than truthiness, so only a literal JSON
        ``true`` counts as done — a truthy but non-boolean ``done`` (e.g. ``1`` or a
        non-empty string) is not mistaken for completion.

        Args:
            operation: The parsed operation JSON object.

        Returns:
            bool: True iff ``done`` is the JSON-true value.
        """
        return operation.get("done") is True

    @staticmethod
    def _hasError(operation: Dict[str, object]) -> bool:
        """Whether the operation JSON carries an ``error`` field.

        Uses presence (``"error" in operation``) rather than truthiness, so an
        empty-but-present ``error: {}`` still counts as an error-bearing operation
        (an empty error object is still a failure the caller must surface, not a
        success).

        Args:
            operation: The parsed operation JSON object.

        Returns:
            bool: True iff an ``error`` key is present.
        """
        return "error" in operation

    @staticmethod
    def _errorResult(errorCode: STTErrorCode) -> TranscriptionResult:
        """Build an ERROR TranscriptionResult with the given code.

        Args:
            errorCode: The provider-neutral failure category.

        Returns:
            TranscriptionResult: ``status=ERROR``, no segments, the given errorCode.
        """
        return TranscriptionResult(status=STTResultStatus.ERROR, segments=(), errorCode=errorCode)
