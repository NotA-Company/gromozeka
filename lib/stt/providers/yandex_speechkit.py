"""Yandex SpeechKit v3 async STT provider (raw httpx wire lifecycle).

This module implements :class:`YandexSpeechKitProvider`, the one concrete
:class:`~lib.stt.abstract.AbstractSTTProvider` for ``lib/stt``. It owns a single
persistent :class:`httpx.AsyncClient` (configured with the injected, already-resolved
:class:`~lib.proxy.ProxyConfig`) and drives the Yandex SpeechKit v3 deferred-recognition
lifecycle end to end: submit → poll → getRecognition → delete.

Per ``docs/plans/lib-stt-v1.md`` §7 (the authoritative wire spec) and §1 (the dependency
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
  §7.4 (retry policy) of ``docs/plans/lib-stt-v1.md``.
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
        _proxyConfig: The injected, already-resolved ProxyConfig (or None).
    """

    # --- Wire endpoints (§7.1 / §7.2) ---------------------------------------
    _SUBMIT_URL: str = "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync"
    _OPERATIONS_BASE_URL: str = "https://operation.api.cloud.yandex.net/operations"
    _GET_RECOGNITION_URL: str = "https://stt.api.cloud.yandex.net/stt/v3/getRecognition"
    _DELETE_RECOGNITION_URL: str = "https://stt.api.cloud.yandex.net/stt/v3/deleteRecognition"

    def __init__(
        self,
        *,
        proxyConfig: Optional[ProxyConfig] = None,
        apiKey: str,
        folderId: str,
        model: str = "general",
        language: str | Sequence[str] = "ru-RU",
        requestTimeoutSeconds: float = 30.0,
        operationBudgetSeconds: float = 180.0,
        pollIntervalSeconds: float = 2.0,
        maxPollIntervalSeconds: float = 10.0,
        maxPolls: int = 100,
        maxRetries: int = 3,
        retryBackoffSeconds: float = 1.0,
        maxResultBytes: int = DEFAULT_MAX_RESULT_BYTES,
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
            language: BCP-47 language code for the WHITELIST restriction. Defaults to
                ``"ru-RU"``.
            proxyConfig: Already-resolved :class:`~lib.proxy.ProxyConfig` (the
                dependency-firewall seam — resolved in the service layer via
                ``ProxyService.resolveProxy``), or ``None`` for no proxy. Spread into
                the ``httpx.AsyncClient`` via ``toKwargs()``.
            requestTimeoutSeconds: Per-httpx-request timeout in seconds (§8.1: 30 s).
            operationBudgetSeconds: Wall-clock operation budget in seconds across
                submit + poll + fetch (§7.2/§7.4: 180 s). Best-effort deletion runs
                outside this budget.
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

        Raises:
            ValueError: If required credentials are missing/empty, any required string
                parameter contains an unresolved ``${…}`` placeholder (indicating a
                missing environment variable), any numeric limit is non-positive, or
                ``maxPollIntervalSeconds < pollIntervalSeconds``
                (startup validation, load-bearing contract #2).

        Returns:
            None
        """
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

        self._apiKey: str = apiKey
        self._folderId: str = folderId
        self._model: str = model
        self._language: Sequence[str] = [language] if isinstance(language, str) else list(language)
        self._proxyConfig: Optional[ProxyConfig] = proxyConfig
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

        # Dependency-firewall seam #1 (§1/§7.2): spread the already-resolved proxy
        # config into the persistent client exactly like lib.yandex_search.client and
        # lib.openweathermap.client. When proxyConfig is None, no proxy kwargs spread.
        # Typed as ProxyKwargs (a total=False TypedDict) so spreading into the httpx
        # client is type-checked the same way lib.yandex_search.client does it.
        proxyKwargs: ProxyKwargs = proxyConfig.toKwargs() if proxyConfig is not None else ProxyKwargs()
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

    async def transcribe(self, audio: ExtractedAudio) -> TranscriptionResult:
        """Transcribe format-aware ExtractedAudio through the full Yandex v3 lifecycle.

        Runs submit (no retry) → poll until done → getRecognition fetch →
        :func:`~lib.stt.providers.yandex_events.parseRecognitionEvents` parse, then a
        best-effort deleteRecognition. The submit + poll + fetch are bounded by the
        operation budget (§7.4); the delete runs outside it and never invalidates a
        successful transcript.

        **Never raises** (load-bearing contract #2): every expected failure returns
        ``TranscriptionResult(status=ERROR, errorCode=...)``. A genuinely unexpected
        exception is also caught and mapped to PROVIDER_ERROR.

        Args:
            audio: The format-aware audio after negotiation. ``audio.container`` drives
                the ``container_audio.container_audio_type`` field dynamically.

        Returns:
            TranscriptionResult: FINAL/NO_SPEECH from the parsed recognition result, or
            ERROR (PROVIDER_ERROR for transport/timeout/operation errors; PROTOCOL_ERROR
            surfaced from the parser for malformed result bodies).
        """
        operationId: Optional[str] = None
        try:
            # §7.4: the 180-second operation budget "starts immediately before submit
            # and includes submit, polling, and the successful result fetch".
            async with asyncio.timeout(self._operationBudgetSeconds):
                operationId = await self._submit(audio)
                recognitionBytes = await self._pollAndFetch(operationId)
        except _ProviderFailure as failure:
            logger.warning("Yandex STT transcribe failed (%s): %s", failure.errorCode, failure)
            return self._errorResult(failure.errorCode)
        except TimeoutError:
            logger.warning(
                "Yandex STT operation budget (%ss) exhausted; operationId=%s",
                self._operationBudgetSeconds,
                operationId,
            )
            return self._errorResult(STTErrorCode.PROVIDER_ERROR)
        except Exception:  # noqa: BLE001 — the never-raise boundary (contract #2)
            logger.exception("Yandex STT unexpected transcribe failure; operationId=%s", operationId)
            return self._errorResult(STTErrorCode.PROVIDER_ERROR)
        finally:
            # Best-effort cleanup runs whenever an operation was created, regardless of
            # outcome. It is OUTSIDE the operation budget and never raises.
            #
            # Intentional ordering vs §7.2 step 5 ("after a successful fetch AND
            # parse, best-effort DELETE"): the delete is run here in ``finally`` —
            # i.e. after the fetch succeeded but BEFORE parse, AND even when the
            # submit/poll path raised (no fetch happened). This is deliberate:
            #   - retention reduction should happen regardless of parse outcome (the
            #     recognised bytes are already in memory, so the operation object is
            #     no longer needed for correctness);
            #   - the delete is best-effort AND idempotent, so a redundant delete on
            #     an already-deleted/erroring operation is a no-op;
            #   - parse cannot fail catastrophically because the parser honours the
            #     never-raise guard (contract #2), so deferring parse past the delete
            #     cannot lose a retrievable transcript.
            # Do NOT "fix" this to match the literal §7.2 wording.
            if operationId is not None:
                await self._bestEffortDelete(operationId)

        # Parse stays OUTSIDE the operation budget (it is fast, in-memory, and §7.4
        # lists only submit/poll/fetch as budgeted) but INSIDE the never-raise
        # boundary — an unexpected parse failure (e.g. a deeply-nested JSON body that
        # trips CPython's recursion limit, or any other exception not in the parser's
        # caught tuple) is mapped to PROTOCOL_ERROR rather than escaping transcribe
        # (load-bearing contract #2).
        try:
            result = parseRecognitionEvents(recognitionBytes, self._maxResultBytes)
        except Exception:  # noqa: BLE001 — defense-in-depth for the parse path too
            logger.exception("Yandex STT unexpected parse failure; operationId=%s", operationId)
            return self._errorResult(STTErrorCode.PROTOCOL_ERROR)
        if result.status is STTResultStatus.ERROR:
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

    # ------------------------------------------------------------------ #
    # Private lifecycle helpers
    # ------------------------------------------------------------------ #

    async def _submit(self, audio: ExtractedAudio) -> str:
        """Submit the audio for deferred recognition (§7.1). NEVER retried (§7.4).

        Builds the protobuf-JSON body with ``container_audio.container_audio_type`` set
        dynamically from ``audio.container`` (the wire label), base64-encodes the audio
        bytes as ``content``, and POSTs to ``recognizeFileAsync`` with the auth headers.

        Args:
            audio: The format-aware audio after negotiation.

        Returns:
            str: The Yandex operation ID parsed from the submit response.

        Raises:
            _ProviderFailure: PROVIDER_ERROR on a non-2xx response, transport error,
                unparseable JSON, or a response missing the operation ID.
        """
        body: Dict[str, object] = self._buildSubmitBody(audio)
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

    def _buildSubmitBody(self, audio: ExtractedAudio) -> Dict[str, object]:
        """Build the protobuf-JSON recognizeFileAsync body (§7.1).

        The ``container_audio.container_audio_type`` is set DYNAMICALLY from
        ``audio.container`` (the wire label — the :class:`STTAudioContainerType` string
        values ARE the proto labels). The base64-encoded audio bytes go in ``content``.

        Args:
            audio: The format-aware audio after negotiation.

        Returns:
            Dict[str, object]: The protobuf-JSON submit body.
        """
        encodedContent: str = base64.b64encode(audio.data).decode("ascii")
        return {
            "content": encodedContent,
            "recognition_model": {
                "model": self._model,
                "audio_format": {
                    "container_audio": {"container_audio_type": audio.container.toYandexSpeechKit()},
                },
                "language_restriction": {
                    "restriction_type": "WHITELIST",
                    "language_code": self._language,
                },
                "text_normalization": {"literature_text": True},
            },
        }

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

    # ------------------------------------------------------------------ #
    # Private timing / parsing helpers
    # ------------------------------------------------------------------ #

    def _pollDelay(self, attempt: int) -> float:
        """Exponential poll backoff, capped at ``maxPollIntervalSeconds`` (§8.1).

        Args:
            attempt: The zero-based poll attempt index.

        Returns:
            float: The delay in seconds before the next poll.
        """
        return min(self._pollIntervalSeconds * (2**attempt), self._maxPollIntervalSeconds)

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
        return min(self._retryBackoffSeconds * (2**attempt), self._maxPollIntervalSeconds)

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
