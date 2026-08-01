"""Golden-HTTP tests for the Yandex SpeechKit v3 provider (§7 / §9).

Covers (per ``docs/plans/lib-stt-v1.md`` §7.1/§7.2/§7.4 and the §9 test matrix) the
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

import base64
import json
from typing import Callable, Dict, List
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from lib.proxy import ProxyConfig, ProxyHelper, ProxyType
from lib.stt.models import (
    ExtractedAudio,
    STTAudioContainerType,
    STTErrorCode,
    STTResultStatus,
)
from lib.stt.providers.yandex_speechkit import YandexSpeechKitProvider

# Fast lifecycle timings so no test waits on real wall-clock backoff. The operation
# budget is generous enough that only maxPolls / explicit status codes drive outcomes.
_FAST_TIMINGS: Dict[str, object] = {
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
    kwargs: Dict[str, object] = {"apiKey": "test-key", "folderId": "test-folder", **_FAST_TIMINGS, **overrides}
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
    submitRequests: List[httpx.Request] = []
    deleteRequests: List[httpx.Request] = []

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
    branch): here a tiny ``operationBudgetSeconds`` plus a poll interval that exceeds
    it forces the ``except TimeoutError`` branch (~line 303) to fire during the
    inter-poll sleep. No real multi-second wait — the 0.05 s budget interrupts the
    0.5 s sleep almost immediately.

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

    # pollIntervalSeconds (0.5) exceeds the operation budget (0.05): the first
    # non-done poll schedules a 0.5 s sleep during which the budget fires.
    provider = await _provider(
        handler,
        operationBudgetSeconds=0.05,
        pollIntervalSeconds=0.5,
        maxPollIntervalSeconds=0.5,
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
    capturedBody: Dict[str, object] = {}

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
def testConstructorRejectsNonPositiveOrContradictoryLimits(kwargs: Dict[str, object], match: str) -> None:
    """Non-positive / contradictory numeric limits raise ValueError.

    Args:
        kwargs: The constructor overrides to apply.
        match: The expected error-message fragment.

    Returns:
        None
    """
    base: Dict[str, object] = {"apiKey": "k", "folderId": "f", **_FAST_TIMINGS}
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
def testConstructorRejectsUnresolvedPlaceholders(kwargs: Dict[str, object], match: str) -> None:
    """Unresolved ${...} placeholders in string params raise ValueError.

    Args:
        kwargs: The constructor overrides to apply (one param with a placeholder).
        match: The expected error-message fragment (the param name).

    Returns:
        None
    """
    base: Dict[str, object] = {"apiKey": "k", "folderId": "f", "model": "general", "language": "ru-RU", **_FAST_TIMINGS}
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
    capturedRequest: List[httpx.Request] = []

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
