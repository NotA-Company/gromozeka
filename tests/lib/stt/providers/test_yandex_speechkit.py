"""Golden-HTTP tests for the Yandex SpeechKit v3 provider (§7 / §9).

Covers (per ``docs/design/lib-stt-v1.md`` §7.1/§7.2/§7.4 and the §9 test matrix) the
provider's full submit→poll→getRecognition→delete lifecycle using ``httpx.MockTransport``
ONLY — no real network (§9). The fixtures assert the parsing/wire LOGIC (event
semantics, dynamic ``container_audio_type``, never-retry submit, idempotent-GET retry,
best-effort delete), not any provisional ``getRecognition`` framing (load-bearing
contract #4).

Test cases:
- Happy path: submit 200 → poll done:false then done:true → getRecognition finals →
  FINAL parsed via the real ``parseRecognitionEvents`` → delete 204.
- Submit non-2xx (401/429/500) → ERROR; submit is NEVER retried (single POST).
- Poll retry: poll returns 429 once then succeeds → result still produced.
- Poll-budget exhaustion (maxPolls): poll never done → ERROR.
- Operation error (done:true with ``error``) → ERROR.
- getRecognition parse variants: finals → FINAL; empty body → NO_SPEECH.
- ``container_audio_type`` dynamic (parametrized OGG_OPUS/MP3/WAV).
- Proxy injection: the injected ProxyConfig is spread into the httpx client.
- aclose: closes the client; transcribe-after-aclose → ERROR (never raises).
- Best-effort delete failure does not discard a successful transcript.
- Never-raise: a transport error and an unexpected exception both → ERROR.
- Constructor validation raises on missing credentials / non-positive limits.

Note on the poll-exhaustion error code: §4 of the plan states the Yandex provider
produces PROVIDER_ERROR (for "exhausted ... timeout") and that ADMISSION_TIMEOUT is
"Produced by STTService; never raised inside lib/stt". The operation-budget /
maxPolls exhaustion is therefore mapped to PROVIDER_ERROR (not ADMISSION_TIMEOUT),
following §4 over the looser wording in the phase task's test-matrix bullet.
"""

import asyncio
import base64
import json
from datetime import datetime
from typing import Callable, Optional, TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from lib.proxy import ProxyConfig, ProxyHelper, ProxyType
from lib.stats.stats_storage import StatsStorage
from lib.stt.models import (
    ExtractedAudio,
    STTAudioContainerType,
    STTErrorCode,
    STTResultStatus,
)
from lib.stt.providers.yandex_object_storage import YandexObjectStorage
from lib.stt.providers.yandex_speechkit import YandexSpeechKitProvider

# Fast lifecycle timings so no test waits on real wall-clock backoff. The operation
# budget is generous enough that only maxPolls / explicit status codes drive outcomes.
_FAST_TIMINGS: dict[str, object] = {
    "requestTimeoutSeconds": 5.0,
    "operationBudgetSeconds": 10.0,
    "pollIntervalSeconds": 0.0,
    "maxPollIntervalSeconds": 0.0,
    "maxRetries": 2,
    "retryBackoffSeconds": 0.0,
}

_SUBMIT_PATH: str = "/stt/v3/recognizeFileAsync"
_GET_RECOGNITION_PATH: str = "/stt/v3/getRecognition"
_DELETE_RECOGNITION_PATH: str = "/stt/v3/deleteRecognition"


# ============================================================================
# Fixture builders
# ============================================================================


def _audio(container: STTAudioContainerType = STTAudioContainerType.OGG_OPUS) -> ExtractedAudio:
    """Build a minimal ExtractedAudio for the given container.

    Args:
        container: The container type to set on the audio.

    Returns:
        ExtractedAudio: A mono 16 kHz clip with placeholder bytes.
    """
    return ExtractedAudio(
        container=container,
        channels=1,
        sampleRate=16000,
        data=b"fake-audio-bytes",
        durationMs=1000,
    )


def _finalEventBytes(
    text: str = "hello world",
    startMs: int = 0,
    endMs: int = 1500,
) -> bytes:
    """Build a single-final recognition body (the provisional streaming-JSON shape).

    Args:
        text: The final segment text.
        startMs: The segment start time in milliseconds.
        endMs: The segment end time in milliseconds.

    Returns:
        bytes: A UTF-8 event stream with one wrapped final event.
    """
    event = {
        "result": {
            "final": {
                "alternatives": [
                    {"text": text, "startTimeMs": startMs, "endTimeMs": endMs},
                ]
            }
        }
    }
    return (json.dumps(event) + "\n").encode("utf-8")


async def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
    **overrides: object,
) -> YandexSpeechKitProvider:
    """Construct a provider whose httpx client uses a MockTransport handler.

    The provider builds a real client in ``__init__`` (per §7.2); this helper closes
    that unused client and swaps in one wired to ``handler``, so no real network is
    touched (§9).

    Args:
        handler: A callable ``(httpx.Request) -> httpx.Response`` for MockTransport.
        **overrides: Extra constructor kwargs (merged over the fast timings).

    Returns:
        YandexSpeechKitProvider: A provider ready for ``transcribe``.
    """
    kwargs: dict[str, object] = {"apiKey": "test-key", "folderId": "test-folder", **_FAST_TIMINGS, **overrides}
    provider = YandexSpeechKitProvider(**kwargs)  # type: ignore[arg-type]
    await provider.aclose()
    provider._httpClient = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


# ============================================================================
# Happy path
# ============================================================================


async def testHappyPathYieldsFinalResult() -> None:
    """Submit→poll(done false→true)→getRecognition→delete produces a FINAL result.

    Returns:
        None
    """
    pollCount = 0
    submitRequests: list[httpx.Request] = []
    deleteRequests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal pollCount
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            submitRequests.append(request)
            return httpx.Response(200, json={"id": "op-123", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            pollCount += 1
            done = pollCount >= 2
            return httpx.Response(200, json={"id": "op-123", "done": done})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("recognized text", 0, 2000))
        if request.method == "DELETE" and request.url.path == _DELETE_RECOGNITION_PATH:
            deleteRequests.append(request)
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _provider(handler)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL
    assert len(result.segments) == 1
    assert result.segments[0].text == "recognized text"
    assert result.segments[0].startMs == 0
    assert result.segments[0].endMs == 2000
    # Submit happened once, delete happened once with the operation_id query param.
    assert len(submitRequests) == 1
    assert len(deleteRequests) == 1
    assert deleteRequests[0].url.params.get("operation_id") == "op-123"


# ============================================================================
# Submit error — never retried (§7.4)
# ============================================================================


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def testSubmitNon2xxYieldsErrorAndIsNotRetried(status: int) -> None:
    """A non-2xx submit yields ERROR and is NEVER retried (single POST).

    Args:
        status: The HTTP status the submit endpoint returns.

    Returns:
        None
    """
    postCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal postCount
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            postCount += 1
            return httpx.Response(status)
        return httpx.Response(404)

    provider = await _provider(handler, maxRetries=5)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR
    assert postCount == 1, "submit must NOT be retried regardless of maxRetries"


# ============================================================================
# Poll retry — idempotent GET retries 429 (§7.4)
# ============================================================================


async def testPollTransient429IsRetriedAndSucceeds() -> None:
    """A single 429 on the poll GET is retried (idempotent) and the result is produced.

    Returns:
        None
    """
    pollGetCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal pollGetCount
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            pollGetCount += 1
            if pollGetCount == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("after retry", 100, 900))
        if request.method == "DELETE" and request.url.path == _DELETE_RECOGNITION_PATH:
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _provider(handler)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].text == "after retry"
    # The first poll GET returned 429 and was retried within the same logical poll.
    assert pollGetCount >= 2


# ============================================================================
# Poll-budget exhaustion (maxPolls) — PROVIDER_ERROR (§4, not ADMISSION_TIMEOUT)
# ============================================================================


async def testMaxPollsExhaustedYieldsProviderError() -> None:
    """Polling that never reaches done within maxPolls yields ERROR/PROVIDER_ERROR.

    §4 reserves ADMISSION_TIMEOUT for STTService's admission wait (never inside
    lib/stt); the provider maps operation-budget/maxPolls exhaustion to PROVIDER_ERROR.

    Returns:
        None
    """
    pollGetCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal pollGetCount
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            pollGetCount += 1
            return httpx.Response(200, json={"id": "op-1", "done": False})
        return httpx.Response(404)

    provider = await _provider(handler, maxPolls=2)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR
    assert pollGetCount == 2


# ============================================================================
# Operation-budget wall-clock timeout (asyncio.timeout) → PROVIDER_ERROR (§7.4)
# ============================================================================


async def testOperationBudgetTimeoutYieldsProviderError() -> None:
    """The wall-clock ``asyncio.timeout`` budget path yields ERROR/PROVIDER_ERROR.

    Complements ``testMaxPollsExhaustedYieldsProviderError`` (the count-exhaustion
    branch): here a small ``operationBudgetSeconds`` plus a poll interval that exceeds
    it forces the ``except TimeoutError`` branch to fire during the inter-poll sleep.
    The margins are deliberately wide (0.5 s budget vs 1.0 s poll sleep) so CI
    scheduling jitter cannot mask or fake the timeout.

    Returns:
        None
    """
    pollGetCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal pollGetCount
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            pollGetCount += 1
            return httpx.Response(200, json={"id": "op-1", "done": False})
        return httpx.Response(404)

    # pollIntervalSeconds (1.0) exceeds the operation budget (0.5): the first
    # non-done poll schedules a 1.0 s sleep during which the budget fires.
    provider = await _provider(
        handler,
        operationBudgetSeconds=0.5,
        pollIntervalSeconds=1.0,
        maxPollIntervalSeconds=1.0,
    )
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR
    assert pollGetCount >= 1, "the wall-clock budget must fire after at least one poll"


# ============================================================================
# Operation error (done:true with error) → PROVIDER_ERROR
# ============================================================================


async def testOperationErrorYieldsProviderError() -> None:
    """An operation that completes with an ``error`` field yields ERROR/PROVIDER_ERROR.

    Returns:
        None
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True, "error": {"code": 3, "message": "bad audio"}})
        return httpx.Response(404)

    provider = await _provider(handler)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR


# ============================================================================
# getRecognition parse variants (parseRecognitionEvents wiring)
# ============================================================================


async def testRecognitionFinalsYieldFinalResult() -> None:
    """A getRecognition body with finals yields FINAL (wired through parseRecognitionEvents).

    Returns:
        None
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("a final segment", 500, 1500))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _provider(handler)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].text == "a final segment"


async def testEmptyRecognitionBodyYieldsNoSpeech() -> None:
    """An empty getRecognition body yields NO_SPEECH.

    Returns:
        None
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=b"")
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _provider(handler)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.NO_SPEECH
    assert result.segments == ()
    assert result.errorCode is None


# ============================================================================
# container_audio_type dynamic (parametrized OGG_OPUS / MP3 / WAV)
# ============================================================================


@pytest.mark.parametrize(
    "container",
    [STTAudioContainerType.OGG_OPUS, STTAudioContainerType.MP3, STTAudioContainerType.WAV],
)
async def testSubmitContainerAudioTypeTracksExtractedAudio(container: STTAudioContainerType) -> None:
    """The submit body's container_audio_type matches ExtractedAudio.container.

    Args:
        container: The container to set on the ExtractedAudio.

    Returns:
        None
    """
    capturedBody: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            capturedBody.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("x", 0, 1))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _provider(handler)
    try:
        await provider.transcribe(_audio(container))
    finally:
        await provider.aclose()

    recognitionModel = capturedBody["recognition_model"]
    assert isinstance(recognitionModel, dict)
    audioFormat = recognitionModel["audio_format"]
    assert isinstance(audioFormat, dict)
    containerAudio = audioFormat["container_audio"]
    assert isinstance(containerAudio, dict)
    assert containerAudio["container_audio_type"] == container.toYandexSpeechKit()
    # The base64 content is present and decodes back to the audio bytes.
    encodedContent = capturedBody["content"]
    assert isinstance(encodedContent, str)
    assert base64.b64decode(encodedContent) == b"fake-audio-bytes"


# ============================================================================
# Proxy injection (dependency-firewall seam #1, §1)
# ============================================================================


async def testProxyConfigIsSpreadIntoHttpClient() -> None:
    """The injected ProxyConfig is spread into the httpx.AsyncClient via toKwargs().

    Returns:
        None
    """
    helper = ProxyHelper.getInstance()
    # The autouse ``resetProxyHelperSingleton`` fixture sets the global proxy to
    # disabled before each test; enable it (type NONE) so the per-service HTTP
    # proxy survives ProxyConfig.getCombined().
    helper.setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
    try:
        proxyConfig = ProxyConfig(
            proxyType=ProxyType.HTTP,
            address="http://proxy:8080",
            user="u",
            password="p",
            enabled=True,
        )

        with patch("lib.stt.providers.yandex_speechkit.httpx.AsyncClient") as mockCtor:
            mockCtor.return_value = AsyncMock()
            YandexSpeechKitProvider(
                apiKey="k",
                folderId="f",
                proxyConfig=proxyConfig,
            )

        mockCtor.assert_called_once()
        kwargs = mockCtor.call_args.kwargs
        assert kwargs.get("proxy") == "http://u:p@proxy:8080"
        assert isinstance(kwargs.get("timeout"), httpx.Timeout)
    finally:
        # Restore the disabled default the autouse fixture set up. The fixture ALSO
        # resets the singleton after each test, but this finally is defensive against
        # ordering-sensitive neighbours should the enabled-state leak ever widen.
        helper.setGlobalProxyConfig({"enabled": False})


async def testNoProxyByDefaultSpreadsEmptyKwargs() -> None:
    """With proxyConfig=None, no proxy kwarg is spread into the httpx client.

    Returns:
        None
    """
    with patch("lib.stt.providers.yandex_speechkit.httpx.AsyncClient") as mockCtor:
        mockCtor.return_value = AsyncMock()
        YandexSpeechKitProvider(apiKey="k", folderId="f")

    mockCtor.assert_called_once()
    kwargs = mockCtor.call_args.kwargs
    assert "proxy" not in kwargs
    assert "transport" not in kwargs


# ============================================================================
# supportedInputFormats — OGG_OPUS first
# ============================================================================


def testSupportedInputFormatsOggOpusFirst() -> None:
    """supportedInputFormats is (OGG_OPUS, MP3, WAV) — OGG_OPUS first.

    Returns:
        None
    """
    with patch("lib.stt.providers.yandex_speechkit.httpx.AsyncClient") as mockCtor:
        mockCtor.return_value = AsyncMock()
        provider = YandexSpeechKitProvider(apiKey="k", folderId="f")
    formats = provider.supportedInputFormats()
    assert [f.container for f in formats] == [
        STTAudioContainerType.OGG_OPUS,
        STTAudioContainerType.MP3,
        STTAudioContainerType.WAV,
    ]


# ============================================================================
# aclose — closes the client; transcribe-after-aclose never raises (§7)
# ============================================================================


async def testAcloseClosesClient() -> None:
    """aclose() closes the httpx client (idempotent; no leak).

    Returns:
        None
    """
    provider = await _provider(lambda request: httpx.Response(404))
    await provider.aclose()  # should not raise
    # Idempotent: a second aclose is safe.
    await provider.aclose()


async def testTranscribeAfterAcloseReturnsErrorNotRaise() -> None:
    """Calling transcribe after aclose returns ERROR rather than raising.

    The closed client raises RuntimeError on send; the never-raise boundary maps it to
    PROVIDER_ERROR.

    Returns:
        None
    """
    provider = await _provider(lambda request: httpx.Response(404))
    await provider.aclose()
    result = await provider.transcribe(_audio())
    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR


# ============================================================================
# Best-effort delete failure does not discard a successful transcript (§7.2/§7.4)
# ============================================================================


async def testDeleteFailureDoesNotInvalidateSuccess() -> None:
    """A failing best-effort delete does not turn a successful transcription into ERROR.

    Returns:
        None
    """
    deleteCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal deleteCount
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("survives delete failure", 0, 500))
        if request.method == "DELETE" and request.url.path == _DELETE_RECOGNITION_PATH:
            deleteCount += 1
            return httpx.Response(500)
        return httpx.Response(404)

    provider = await _provider(handler)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].text == "survives delete failure"
    assert deleteCount == 1


# ============================================================================
# Never-raise (load-bearing contract #2)
# ============================================================================


async def testTransportErrorDuringSubmitYieldsErrorNotRaise() -> None:
    """A transport error (ConnectError) during submit yields ERROR, never raises.

    Returns:
        None
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = await _provider(handler)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR


async def testUnexpectedExceptionYieldsErrorNotRaise() -> None:
    """An unexpected (non-httpx) exception is caught by the never-raise boundary.

    Returns:
        None
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom")

    provider = await _provider(handler)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR


async def testMalformedSubmitResponseYieldsError() -> None:
    """A submit 200 with a missing operation id yields ERROR/PROVIDER_ERROR.

    Returns:
        None
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"unexpected": "shape"})
        return httpx.Response(404)

    provider = await _provider(handler)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR


# ============================================================================
# Parse-path never-raise regression (contract #2 gap)
# ============================================================================


async def testParsePathUnexpectedExceptionNeverRaisesRegression() -> None:
    """Regression: an unexpected exception from parseRecognitionEvents must not escape.

    Before the fix, ``parseRecognitionEvents`` was called OUTSIDE the never-raise
    ``try/except`` block in ``transcribe`` (the boundary wrapped only submit/poll/
    fetch). Any exception not in the parser's caught tuple
    ``(UnicodeDecodeError, ValueError, TypeError, KeyError, IndexError,
    ArithmeticError)`` therefore escaped ``transcribe`` and violated load-bearing
    contract #2. The reviewer's threat-model vector is ``RecursionError`` (a
    ``RuntimeError`` subclass) from a deeply-nested JSON body.

    CPython's C JSON scanner became iterative for deep nesting in 3.13+, so a real
    deeply-nested body no longer trips the recursion limit on this runtime — the
    boundary is therefore exercised by injecting the exact exception type the threat
    model posits, which is deterministic across every Python build. Before the fix
    this raises out of ``transcribe``; after the fix it returns
    ``ERROR/PROTOCOL_ERROR`` (a parse-side surprise is a malformed-provider-response
    failure).

    Returns:
        None
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("x", 0, 1))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _provider(handler)
    try:
        with patch(
            "lib.stt.providers.yandex_speechkit.parseRecognitionEvents",
            side_effect=RecursionError("simulated deep-nesting recursion"),
        ):
            result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


async def testDeeplyNestedRecognitionBodyNeverRaises() -> None:
    """A deeply-nested getRecognition body never escapes transcribe (portable guard).

    Complements ``testParsePathUnexpectedExceptionNeverRaisesRegression`` with the
    reviewer's real-payload vector: a body of ``{"a":{"a":{...}}}`` nested far beyond
    the default recursion limit (and well under the 5 MiB result-byte cap). The
    never-raise contract (load-bearing #2) must hold regardless of scanner
    implementation:

    - On iterative-scanner builds (CPython 3.13+) the body parses cleanly and, having
      no ``final``/``finalRefinement`` events, yields ``NO_SPEECH``.
    - On recursive-scanner builds (CPython ≤3.12) the body raises ``RecursionError``
      inside the parser; the never-raise guard maps it to ``ERROR/PROTOCOL_ERROR``.

    Either way ``transcribe`` returns a valid result and never raises.

    Returns:
        None
    """
    # 5000 levels of nesting exceed every CPython recursion limit, while staying
    # well under the 5 MiB result-byte cap (~30 KiB).
    nestedBody: bytes = (b'{"a":' * 5000) + b"0" + (b"}" * 5000)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=nestedBody)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _provider(handler)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    # NO_SPEECH on iterative-scanner builds; PROTOCOL_ERROR (ERROR) on recursive
    # builds — both are valid non-raising outcomes for this adversarial body.
    assert result.status in (STTResultStatus.NO_SPEECH, STTResultStatus.ERROR)
    if result.status is STTResultStatus.ERROR:
        assert result.errorCode is STTErrorCode.PROTOCOL_ERROR


# ============================================================================
# Constructor validation (the only permitted raise site, §4)
# ============================================================================


def testConstructorRejectsMissingApiKey() -> None:
    """A missing apiKey raises ValueError (startup validation).

    Returns:
        None
    """
    with pytest.raises(ValueError, match="apiKey"):
        with patch("lib.stt.providers.yandex_speechkit.httpx.AsyncClient"):
            YandexSpeechKitProvider(apiKey="", folderId="f")


def testConstructorRejectsMissingFolderId() -> None:
    """A missing folderId raises ValueError (startup validation).

    Returns:
        None
    """
    with pytest.raises(ValueError, match="folderId"):
        with patch("lib.stt.providers.yandex_speechkit.httpx.AsyncClient"):
            YandexSpeechKitProvider(apiKey="k", folderId="")


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"requestTimeoutSeconds": 0}, "requestTimeoutSeconds"),
        ({"operationBudgetSeconds": 0}, "operationBudgetSeconds"),
        ({"maxPolls": 0}, "maxPolls"),
        ({"maxRetries": -1}, "maxRetries"),
        ({"maxResultBytes": 0}, "maxResultBytes"),
        ({"maxPollIntervalSeconds": 1, "pollIntervalSeconds": 2}, "maxPollIntervalSeconds"),
        ({"pollIntervalSeconds": -1}, "pollIntervalSeconds"),
        ({"retryBackoffSeconds": -1}, "retryBackoffSeconds"),
    ],
)
def testConstructorRejectsNonPositiveOrContradictoryLimits(kwargs: dict[str, object], match: str) -> None:
    """Non-positive / contradictory numeric limits raise ValueError.

    Args:
        kwargs: The constructor overrides to apply.
        match: The expected error-message fragment.

    Returns:
        None
    """
    base: dict[str, object] = {"apiKey": "k", "folderId": "f", **_FAST_TIMINGS}
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        with patch("lib.stt.providers.yandex_speechkit.httpx.AsyncClient"):
            YandexSpeechKitProvider(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"apiKey": "${YC_API_KEY}"}, "apiKey"),
        ({"folderId": "${YC_FOLDER_ID}"}, "folderId"),
        ({"model": "${STT_MODEL}"}, "model"),
        ({"language": "${STT_LANGUAGE}"}, "language"),
    ],
)
def testConstructorRejectsUnresolvedPlaceholders(kwargs: dict[str, object], match: str) -> None:
    """Unresolved ${...} placeholders in string params raise ValueError.

    Args:
        kwargs: The constructor overrides to apply (one param with a placeholder).
        match: The expected error-message fragment (the param name).

    Returns:
        None
    """
    base: dict[str, object] = {"apiKey": "k", "folderId": "f", "model": "general", "language": "ru-RU", **_FAST_TIMINGS}
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        with patch("lib.stt.providers.yandex_speechkit.httpx.AsyncClient"):
            YandexSpeechKitProvider(**base)  # type: ignore[arg-type]


def testConstructorRejectsMissingModel() -> None:
    """A missing model raises ValueError (startup validation).

    Returns:
        None
    """
    with pytest.raises(ValueError, match="model"):
        with patch("lib.stt.providers.yandex_speechkit.httpx.AsyncClient"):
            YandexSpeechKitProvider(apiKey="k", folderId="f", model="")


def testConstructorRejectsMissingLanguage() -> None:
    """A missing language raises ValueError (startup validation).

    Returns:
        None
    """
    with pytest.raises(ValueError, match="language"):
        with patch("lib.stt.providers.yandex_speechkit.httpx.AsyncClient"):
            YandexSpeechKitProvider(apiKey="k", folderId="f", language="")


# ============================================================================
# Submit URL / headers (§7.1)
# ============================================================================


async def testSubmitUsesCorrectUrlAndHeaders() -> None:
    """The submit POST targets recognizeFileAsync with Api-Key + x-folder-id headers.

    Returns:
        None
    """
    capturedRequest: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            capturedRequest.append(request)
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("x", 0, 1))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _provider(handler)
    try:
        await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert len(capturedRequest) == 1
    request = capturedRequest[0]
    assert str(request.url) == "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync"
    assert request.headers["Authorization"] == "Api-Key test-key"
    assert request.headers["x-folder-id"] == "test-folder"
    assert request.headers["Content-Type"] == "application/json"


# ============================================================================
# Phase 2: Object Storage construction wiring (design §3.1, §6.1, §6.3)
# ============================================================================


def _constructProvider(**overrides: object) -> YandexSpeechKitProvider:
    """Construct a provider with patched httpx client and given overrides.

    Args:
        **overrides: Extra constructor kwargs merged over the base credentials.

    Returns:
        YandexSpeechKitProvider: A constructed provider (httpx client is a mock).
    """
    base: dict[str, object] = {"apiKey": "test-key", "folderId": "test-folder", **_FAST_TIMINGS}
    base.update(overrides)
    with patch("lib.stt.providers.yandex_speechkit.httpx.AsyncClient") as mockCtor:
        mockCtor.return_value = AsyncMock()
        provider = YandexSpeechKitProvider(**base)  # type: ignore[arg-type]
    return provider


async def testInlineOnlyDefaultObjectStorageNone() -> None:
    """With no OS params, the provider is inline-only and _objectStorage is None.

    Returns:
        None
    """
    provider = _constructProvider()
    try:
        assert provider._objectStorage is None
        assert provider._maxInlineBytes == 41943040
    finally:
        await provider.aclose()


async def testObjectStorageHelperConstructedWhenBucketSet() -> None:
    """With bucket + both keys, _objectStorage is a YandexObjectStorage with correct attrs.

    boto3.client is patched so the real helper logic runs without a real S3 endpoint.

    Returns:
        None
    """
    with patch("lib.stt.providers.yandex_object_storage.boto3") as mockBoto3:
        mockClient = MagicMock()
        mockBoto3.client.return_value = mockClient
        provider = _constructProvider(
            objectStorageBucket="test-bucket",
            objectStorageKeyId="test-key-id",
            objectStorageKeySecret="test-key-secret",
        )
    try:
        assert provider._objectStorage is not None
        assert isinstance(provider._objectStorage, YandexObjectStorage)
        # Verify boto3.client was called with the right S3 args (endpoint, region,
        # credentials). The Config object is constructed at import time before the
        # patch, so we check the non-Config kwargs precisely.
        mockBoto3.client.assert_called_once()
        callKwargs = mockBoto3.client.call_args.kwargs
        assert callKwargs["endpoint_url"] == "https://storage.yandexcloud.net"
        assert callKwargs["region_name"] == "ru-central1"
        assert callKwargs["aws_access_key_id"] == "test-key-id"
        assert callKwargs["aws_secret_access_key"] == "test-key-secret"
        assert "config" in callKwargs
    finally:
        await provider.aclose()


async def testPartialConfigBucketWithoutKeysRejected() -> None:
    """Bucket without both keys raises ValueError (partial config).

    Returns:
        None
    """
    with pytest.raises(ValueError, match="objectStorageKeyId"):
        _constructProvider(objectStorageBucket="b", objectStorageKeyId=None, objectStorageKeySecret=None)

    with pytest.raises(ValueError, match="objectStorageKeyId"):
        _constructProvider(objectStorageBucket="b", objectStorageKeyId="k", objectStorageKeySecret=None)

    with pytest.raises(ValueError, match="objectStorageKeySecret"):
        _constructProvider(objectStorageBucket="b", objectStorageKeyId=None, objectStorageKeySecret="s")


async def testPartialConfigKeysWithoutBucketRejected() -> None:
    """Keys without bucket raises ValueError (partial config).

    Covers both-keys and each single-key alone.

    Returns:
        None
    """
    with pytest.raises(ValueError, match="without objectStorageBucket"):
        _constructProvider(objectStorageBucket=None, objectStorageKeyId="k", objectStorageKeySecret="s")

    with pytest.raises(ValueError, match="without objectStorageBucket"):
        _constructProvider(objectStorageBucket=None, objectStorageKeyId="k", objectStorageKeySecret=None)

    with pytest.raises(ValueError, match="without objectStorageBucket"):
        _constructProvider(objectStorageBucket=None, objectStorageKeyId=None, objectStorageKeySecret="s")


async def testEmptyBucketWithKeysRejected() -> None:
    """objectStorageBucket="" (empty string) + keys raises ValueError.

    An empty bucket is normalized to None, so keys-without-bucket fires. The caller
    should either provide a real bucket name or omit the keys entirely.

    Returns:
        None
    """
    with pytest.raises(ValueError, match="without objectStorageBucket"):
        _constructProvider(objectStorageBucket="", objectStorageKeyId="k", objectStorageKeySecret="s")


async def testEmptyBucketOnlyTreatedAsUnset() -> None:
    """objectStorageBucket="" with no keys is treated as unset → inline-only.

    Returns:
        None
    """
    provider = _constructProvider(objectStorageBucket="", objectStorageKeyId=None, objectStorageKeySecret=None)
    try:
        assert provider._objectStorage is None
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    "kwargs, match",
    [
        (
            {"objectStorageBucket": "b", "objectStorageKeyId": "${YC_S3_KEY_ID}", "objectStorageKeySecret": "s"},
            "objectStorageKeyId",
        ),
        (
            {"objectStorageBucket": "${YC_S3_BUCKET}", "objectStorageKeyId": "k", "objectStorageKeySecret": "s"},
            "objectStorageBucket",
        ),
        (
            {"objectStorageBucket": "b", "objectStorageKeyId": "k", "objectStorageKeySecret": "${YC_S3_SECRET}"},
            "objectStorageKeySecret",
        ),
    ],
)
async def testUnresolvedPlaceholderInOsCredsRejected(kwargs: dict[str, object], match: str) -> None:
    """Unresolved ${...} placeholders in OS cred params raise ValueError.

    Args:
        kwargs: The constructor overrides to apply.
        match: The expected error-message fragment.

    Returns:
        None
    """
    with pytest.raises(ValueError, match=match):
        _constructProvider(**kwargs)


@pytest.mark.parametrize(
    "value, match",
    [
        (0, "maxInlineBytes must be positive"),
        (-1, "maxInlineBytes must be positive"),
    ],
)
def testMaxInlineBytesValidation(value: int, match: str) -> None:
    """A non-positive maxInlineBytes raises ValueError (must be positive).

    Args:
        value: The invalid maxInlineBytes value.
        match: The expected error-message fragment.

    Returns:
        None
    """
    with pytest.raises(ValueError, match=match):
        _constructProvider(maxInlineBytes=value)


async def testAcloseClosesObjectStorageHelper() -> None:
    """aclose() awaits _objectStorage.aclose() when the helper is present.

    Returns:
        None
    """
    with patch("lib.stt.providers.yandex_object_storage.boto3") as mockBoto3:
        mockClient = MagicMock()
        mockBoto3.client.return_value = mockClient
        provider = _constructProvider(
            objectStorageBucket="b",
            objectStorageKeyId="k",
            objectStorageKeySecret="s",
        )
    try:
        assert provider._objectStorage is not None
        mockAclose = AsyncMock()
        # YandexObjectStorage.__slots__ forbids shadowing ``aclose`` as an instance
        # attribute; patch the class method instead (same effect, slots-safe).
        with patch.object(YandexObjectStorage, "aclose", mockAclose):
            await provider.aclose()
            mockAclose.assert_awaited_once()
    finally:
        pass  # aclose already called above


async def testAcloseDoesNotCrashWhenObjectStorageNone() -> None:
    """aclose() does not crash when _objectStorage is None (inline-only).

    Returns:
        None
    """
    provider = _constructProvider()
    try:
        assert provider._objectStorage is None
        await provider.aclose()  # must not raise
    finally:
        pass  # aclose already called above


# ============================================================================
# Phase 3: Object Storage routing lifecycle (design §4.3, §4.4, §4.5)
# ============================================================================


def _largeAudio() -> ExtractedAudio:
    """Build an ExtractedAudio whose data exceeds the default maxInlineBytes (41943040).

    Returns:
        ExtractedAudio: A mono 16 kHz clip with data length > maxInlineBytes.
    """
    return ExtractedAudio(
        container=STTAudioContainerType.OGG_OPUS,
        channels=1,
        sampleRate=16000,
        data=b"\x00" * 41943041,
        durationMs=1000,
    )


def _mockObjectStorage(*, uploadFail: bool = False, deleteFail: bool = False) -> AsyncMock:
    """Build a mock YandexObjectStorage with controllable upload/delete behaviour.

    Args:
        uploadFail: When True, ``upload`` raises RuntimeError.
        deleteFail: When True, ``delete`` raises RuntimeError.

    Returns:
        AsyncMock: A mock with ``upload``, ``delete``, and ``aclose`` methods.
    """
    mockOs: AsyncMock = AsyncMock()
    mockOs.aclose = AsyncMock()
    if uploadFail:
        mockOs.upload.side_effect = RuntimeError("upload failed")
    else:
        mockOs.upload.return_value = "https://storage.yandexcloud.net/test-bucket/stt/fake-uuid"
    if deleteFail:
        mockOs.delete.side_effect = RuntimeError("delete failed")
    return mockOs


async def _providerWithOs(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    maxInlineBytes: int = 41943040,
    mockOs: Optional[AsyncMock] = None,
) -> YandexSpeechKitProvider:
    """Construct a provider with Object Storage mock and MockTransport.

    Args:
        handler: A callable ``(httpx.Request) -> httpx.Response`` for MockTransport.
        maxInlineBytes: The inline threshold.
        mockOs: A mock Object Storage; if None, a default (non-failing) mock is used.

    Returns:
        YandexSpeechKitProvider: A provider ready for ``transcribe``.
    """
    kwargs: dict[str, object] = {
        "apiKey": "test-key",
        "folderId": "test-folder",
        **_FAST_TIMINGS,
        "maxInlineBytes": maxInlineBytes,
        "objectStorageBucket": "test-bucket",
        "objectStorageKeyId": "k",
        "objectStorageKeySecret": "s",
    }
    with patch("lib.stt.providers.yandex_object_storage.boto3") as mockBoto3:
        mockBoto3.client.return_value = MagicMock()
        provider = YandexSpeechKitProvider(**kwargs)  # type: ignore[arg-type]
    await provider.aclose()
    if mockOs is not None:
        provider._objectStorage = mockOs
    provider._httpClient = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


# --- Test 1: Inline path unchanged ---


async def testInlinePathUsesContentAndDoesNotCallUpload() -> None:
    """Small audio (below maxInlineBytes) uses inline content, never calls upload.

    The submit body has ``content`` (base64), NO ``uri``; the helper's upload
    is NOT called; object delete is NOT called.  Byte-for-byte v1 behaviour.

    Returns:
        None
    """
    mockOs = _mockObjectStorage()
    capturedBody: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal capturedBody
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            capturedBody = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("inline", 0, 500))
        if request.method == "DELETE" and request.url.path == _DELETE_RECOGNITION_PATH:
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _providerWithOs(handler, mockOs=mockOs)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL
    assert "content" in capturedBody
    assert "uri" not in capturedBody
    assert base64.b64decode(str(capturedBody["content"])) == b"fake-audio-bytes"
    mockOs.upload.assert_not_called()
    mockOs.delete.assert_not_called()


# --- Test 2: OS path submit body ---


async def testOsPathUsesUriAndCallsUpload() -> None:
    """Large audio (>= maxInlineBytes) with OS present uses uri, calls upload.

    The submit body has ``uri`` (the upload return value), NO ``content``.
    ``recognition_model`` block is identical to the inline path.  Upload is
    called once, delete is called once in finally.

    Returns:
        None
    """
    mockOs = _mockObjectStorage()
    capturedBody: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal capturedBody
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            capturedBody = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("os path", 0, 500))
        if request.method == "DELETE" and request.url.path == _DELETE_RECOGNITION_PATH:
            return httpx.Response(204)
        return httpx.Response(404)

    audio = _largeAudio()
    provider = await _providerWithOs(handler, mockOs=mockOs)
    try:
        result = await provider.transcribe(audio)
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL
    assert "uri" in capturedBody
    assert "content" not in capturedBody
    assert capturedBody["uri"] == "https://storage.yandexcloud.net/test-bucket/stt/fake-uuid"
    # recognition_model block is present and structurally identical.
    recognitionModel: dict[str, object] = capturedBody["recognition_model"]  # type: ignore[assignment]
    assert recognitionModel["model"] == "general"
    audioFormat: dict[str, object] = recognitionModel["audio_format"]  # type: ignore[assignment]
    containerAudio: dict[str, object] = audioFormat["container_audio"]  # type: ignore[assignment]
    assert containerAudio["container_audio_type"] == "OGG_OPUS"
    mockOs.upload.assert_awaited_once_with(audio.data)
    mockOs.delete.assert_awaited_once()


# --- Test 3: OS disabled + over-threshold → SOURCE_TOO_LARGE ---


async def testOsDisabledOverThresholdReturnsSourceTooLarge() -> None:
    """OS disabled (None) + over-threshold → ERROR(SOURCE_TOO_LARGE).

    Submit is NOT called; helper is NOT called (it is None).

    Returns:
        None
    """
    postCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal postCount
        if request.method == "POST":
            postCount += 1
        return httpx.Response(404)

    # Provider with OS disabled (no object storage params).
    provider = await _provider(handler, maxInlineBytes=41943040)
    try:
        result = await provider.transcribe(_largeAudio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.SOURCE_TOO_LARGE
    assert postCount == 0


# --- Test 4: Upload failure → OBJECT_STORAGE_ERROR ---


async def testUploadFailureReturnsObjectStorageError() -> None:
    """Upload raises → ERROR(OBJECT_STORAGE_ERROR).  Submit NOT called.

    Returns:
        None
    """
    mockOs = _mockObjectStorage(uploadFail=True)
    postCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal postCount
        if request.method == "POST":
            postCount += 1
        return httpx.Response(404)

    provider = await _providerWithOs(handler, mockOs=mockOs)
    try:
        result = await provider.transcribe(_largeAudio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.OBJECT_STORAGE_ERROR
    assert postCount == 0
    mockOs.delete.assert_not_called()  # upload failed → no objectUri → no delete


# --- Test 5: Object delete is best-effort / never raises ---


async def testObjectDeleteFailureDoesNotInvalidateSuccess() -> None:
    """Object delete raises → transcript still returned successfully.

    The exception is swallowed + logged; the operation delete still runs.

    Returns:
        None
    """
    mockOs = _mockObjectStorage(deleteFail=True)
    deleteOperationCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal deleteOperationCount
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("survives", 0, 500))
        if request.method == "DELETE" and request.url.path == _DELETE_RECOGNITION_PATH:
            deleteOperationCount += 1
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _providerWithOs(handler, mockOs=mockOs)
    try:
        result = await provider.transcribe(_largeAudio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].text == "survives"
    mockOs.upload.assert_awaited_once()
    mockOs.delete.assert_awaited_once()
    # The operation delete still ran.
    assert deleteOperationCount == 1


# --- Test 6: Object delete runs after operation failure ---


async def testObjectDeletedInFinallyAfterOperationFailure() -> None:
    """Upload succeeds, then the operation fails → object IS deleted in finally.

    No leak: the staged object must be cleaned up even when recognition fails.

    Returns:
        None
    """
    mockOs = _mockObjectStorage()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True, "error": {"code": 3}})
        if request.method == "DELETE" and request.url.path == _DELETE_RECOGNITION_PATH:
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _providerWithOs(handler, mockOs=mockOs)
    try:
        result = await provider.transcribe(_largeAudio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.PROVIDER_ERROR
    mockOs.upload.assert_awaited_once()
    mockOs.delete.assert_awaited_once()


# --- Test 7: Upload outside the budget ---


async def testUploadOutsideBudgetNotBoundedByOperationTimeout() -> None:
    """Upload happens BEFORE the asyncio.timeout context (outside the budget).

    A slow upload (with a sleep) should NOT be interrupted by the
    operation-budget timeout.  Assert upload is called before submit.

    Returns:
        None
    """
    callOrder: list[str] = []

    async def slowUpload(data: bytes) -> str:
        """Simulate a slow upload that sleeps longer than the operation budget.

        Args:
            data: The audio bytes (ignored).

        Returns:
            str: A fake URI.
        """
        callOrder.append("upload")
        await asyncio.sleep(1.0)  # 1s upload — longer than the budget
        return "https://storage.yandexcloud.net/test-bucket/stt/fake-uuid"

    mockOs = _mockObjectStorage()
    mockOs.upload.side_effect = slowUpload
    postCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal postCount
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            postCount += 1
            callOrder.append("submit")
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("x", 0, 1))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    # operationBudgetSeconds = 0.5 (500ms) — far shorter than the 1s upload sleep.
    provider = await _providerWithOs(handler, mockOs=mockOs)
    # Override the budget to something smaller than the upload sleep.
    provider._operationBudgetSeconds = 0.5
    try:
        result = await provider.transcribe(_largeAudio())
    finally:
        await provider.aclose()

    # The upload completed (outside the budget) and the submit was reached.
    # If the upload were inside the budget, the 0.5s timeout would have
    # interrupted the 1s upload sleep and we'd get PROVIDER_ERROR.
    assert result.status is STTResultStatus.FINAL
    assert callOrder == ["upload", "submit"], f"Expected upload before submit, got {callOrder}"
    assert postCount == 1


# ============================================================================
# Phase 4: Statistics recording (design §5)
# ============================================================================


class _StatsRecord(TypedDict):
    """One recorded stats event as captured by ``_RecordingStatsStorage``.

    Attributes:
        stats: The numeric stats dict.
        consumerId: The consumer ID (None when not provided).
        labels: The dimension labels (empty when not provided).
    """

    stats: dict[str, float | int]
    consumerId: Optional[str]
    labels: dict[str, str]


class _RecordingStatsStorage(StatsStorage):
    """In-memory fake StatsStorage that records calls for test assertions.

    Attributes:
        records: List of dicts with keys ``stats``, ``consumerId``, ``labels``.
        shouldRaise: When set to an exception, ``record()`` raises it (for
            best-effort testing).
    """

    def __init__(self) -> None:
        """Initialize the recording fake.

        Returns:
            None
        """
        self.records: list[_StatsRecord] = []
        self.shouldRaise: Optional[Exception] = None

    async def record(
        self,
        stats: dict[str, float | int],
        *,
        consumerId: Optional[str] = None,
        labels: Optional[dict[str, str]] = None,
        eventTime: Optional[datetime] = None,
    ) -> None:
        """Append a record for later assertion.

        Args:
            stats: The stats dict.
            consumerId: The consumer ID.
            labels: The labels dict.
            eventTime: Ignored.

        Returns:
            None

        Raises:
            Exception: When ``shouldRaise`` is set (for best-effort testing).
        """
        if self.shouldRaise is not None:
            raise self.shouldRaise
        record: _StatsRecord = {
            "stats": dict(stats),
            "consumerId": consumerId,
            "labels": dict(labels) if labels else {},
        }
        self.records.append(record)

    async def aggregate(self, *, limit: int = 1000, orphanTimeoutSeconds: int = 3600) -> int:
        """No-op for this fake.

        Args:
            limit: Ignored.
            orphanTimeoutSeconds: Ignored.

        Returns:
            int: Always 0.
        """
        return 0


async def _providerWithStats(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    statsStorage: Optional[_RecordingStatsStorage] = None,
    **overrides: object,
) -> YandexSpeechKitProvider:
    """Construct a provider with a recording StatsStorage and MockTransport.

    When ``statsStorage`` is None, the provider uses its default ``NullStatsStorage``
    (no stats recorded).

    Args:
        handler: A callable ``(httpx.Request) -> httpx.Response`` for MockTransport.
        statsStorage: A recording fake; if None, no stats are captured.
        **overrides: Extra constructor kwargs merged over the fast timings.

    Returns:
        YandexSpeechKitProvider: A provider ready for ``transcribe``.
    """
    kwargs: dict[str, object] = {"apiKey": "test-key", "folderId": "test-folder", **_FAST_TIMINGS, **overrides}
    if statsStorage is not None:
        kwargs["statsStorage"] = statsStorage
    provider = YandexSpeechKitProvider(**kwargs)  # type: ignore[arg-type]
    await provider.aclose()
    provider._httpClient = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


def _happyHandler() -> Callable[[httpx.Request], httpx.Response]:
    """Build a handler for the full happy path (submit→poll→fetch→delete).

    Returns:
        Callable: A MockTransport handler.
    """
    pollCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal pollCount
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            pollCount += 1
            return httpx.Response(200, json={"id": "op-1", "done": pollCount >= 2})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("hello world", 0, 2000))
        if request.method == "DELETE" and request.url.path == _DELETE_RECOGNITION_PATH:
            return httpx.Response(204)
        return httpx.Response(404)

    return handler


# --- Test 1: Success records stats ---


async def testStatsRecordedOnSuccess() -> None:
    """A FINAL result triggers exactly one stats record with correct fields.

    Returns:
        None
    """
    stats = _RecordingStatsStorage()
    provider = await _providerWithStats(_happyHandler(), statsStorage=stats)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL
    assert len(stats.records) == 1

    record = stats.records[0]
    assert record["stats"]["generation_stt"] == 1
    assert record["stats"]["request_count"] == 1
    assert record["stats"]["audio_duration_ms"] == 1000  # _audio().durationMs
    assert record["stats"]["elapsed_time"] >= 0
    assert record["stats"]["is_error"] == 0
    assert record["stats"]["status_final"] == 1
    assert record["labels"]["provider"] == "YandexSpeechKitProvider"
    assert record["labels"]["generationType"] == "stt"
    assert record["labels"]["status"] == "final"
    assert record["labels"]["model"] == "general"  # _providerWithStats uses the default model
    # No errorCode label on success — it is only added when result.errorCode is set.
    assert "errorCode" not in record["labels"]


# --- Test 2: ERROR records stats ---


async def testStatsRecordedOnError() -> None:
    """An ERROR result (SOURCE_TOO_LARGE) triggers stats with is_error=1.

    Returns:
        None
    """
    stats = _RecordingStatsStorage()
    postCount = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal postCount
        if request.method == "POST":
            postCount += 1
        return httpx.Response(404)

    # Provider with OS disabled (inline-only) and a large audio → SOURCE_TOO_LARGE.
    provider = await _providerWithStats(handler, statsStorage=stats, maxInlineBytes=41943040)
    try:
        result = await provider.transcribe(_largeAudio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.ERROR
    assert result.errorCode is STTErrorCode.SOURCE_TOO_LARGE
    assert postCount == 0

    assert len(stats.records) == 1
    record = stats.records[0]
    assert record["stats"]["is_error"] == 1
    assert record["stats"]["status_error"] == 1
    assert record["labels"]["status"] == "error"
    assert record["labels"]["errorCode"] == result.errorCode


# --- Test 3: NullStatsStorage default is a no-op ---


async def testNullStatsStorageDefaultIsNoOp() -> None:
    """Provider constructed without statsStorage transcribes successfully (no crash).

    Returns:
        None
    """
    provider = await _providerWithStats(_happyHandler())
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL


# --- Test 4: Best-effort never raises ---


async def testStatsRecordingFailureDoesNotAffectResult() -> None:
    """When the fake's record() raises, transcription still returns the correct result.

    The exception is swallowed + logged; no exception escapes transcribe.

    Returns:
        None
    """
    stats = _RecordingStatsStorage()
    stats.shouldRaise = RuntimeError("stats storage down")
    provider = await _providerWithStats(_happyHandler(), statsStorage=stats)
    try:
        result = await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL
    assert result.segments[0].text == "hello world"


# --- Test 5: consumerId threading ---


async def testConsumerIdForwardedToStatsRecording() -> None:
    """stt(data, consumerId='chat-123') passes consumerId to stats record().

    Returns:
        None
    """
    stats = _RecordingStatsStorage()
    provider = await _providerWithStats(_happyHandler(), statsStorage=stats)
    try:
        await provider.transcribe(_audio(), consumerId="chat-123")
    finally:
        await provider.aclose()

    assert len(stats.records) == 1
    assert stats.records[0]["consumerId"] == "chat-123"


async def testNoConsumerIdDefaultsToNoneInStatsRecording() -> None:
    """stt(data) without consumerId passes None to stats record().

    Returns:
        None
    """
    stats = _RecordingStatsStorage()
    provider = await _providerWithStats(_happyHandler(), statsStorage=stats)
    try:
        await provider.transcribe(_audio())
    finally:
        await provider.aclose()

    assert len(stats.records) == 1
    assert stats.records[0]["consumerId"] is None


# --- Test 6: Stats recording does not interfere with finally cleanup ---


async def testStatsRecordedAndObjectDeleteBothRun() -> None:
    """On the OS path, object delete runs AND stats are recorded — neither blocks the other.

    Returns:
        None
    """
    stats = _RecordingStatsStorage()
    mockOs = _mockObjectStorage()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("os + stats", 0, 500))
        if request.method == "DELETE" and request.url.path == _DELETE_RECOGNITION_PATH:
            return httpx.Response(204)
        return httpx.Response(404)

    provider = await _providerWithOs(handler, mockOs=mockOs)
    provider.statsStorage = stats
    try:
        result = await provider.transcribe(_largeAudio())
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL
    # Object delete ran.
    mockOs.delete.assert_awaited_once()
    # Stats were recorded.
    assert len(stats.records) == 1
    assert stats.records[0]["labels"]["status"] == "final"


# ============================================================================
# Phase 4 ride-along: boundary test for maxInlineBytes (>= semantics)
# ============================================================================


async def testExactMaxInlineBytesRoutesToObjectStorage() -> None:
    """len(audio.data) == maxInlineBytes routes to Object Storage (locks >= semantics).

    The existing _largeAudio is maxInlineBytes+1 (above); this tests the exact
    boundary (==) to lock the >= routing against a future > regression.

    Returns:
        None
    """
    maxInlineBytes = 8
    mockOs = _mockObjectStorage()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == _SUBMIT_PATH:
            return httpx.Response(200, json={"id": "op-1", "done": False})
        if request.method == "GET" and request.url.path.startswith("/operations/"):
            return httpx.Response(200, json={"id": "op-1", "done": True})
        if request.method == "GET" and request.url.path == _GET_RECOGNITION_PATH:
            return httpx.Response(200, content=_finalEventBytes("boundary", 0, 500))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    # Audio with data exactly == maxInlineBytes.
    boundaryAudio = ExtractedAudio(
        container=STTAudioContainerType.OGG_OPUS,
        channels=1,
        sampleRate=16000,
        data=b"\x00" * maxInlineBytes,
        durationMs=100,
    )

    provider = await _providerWithOs(handler, maxInlineBytes=maxInlineBytes, mockOs=mockOs)
    try:
        result = await provider.transcribe(boundaryAudio)
    finally:
        await provider.aclose()

    assert result.status is STTResultStatus.FINAL
    mockOs.upload.assert_awaited_once()
