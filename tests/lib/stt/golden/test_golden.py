"""Golden-data replayer tests for the Yandex SpeechKit STT provider.

These tests replay recorded Yandex SpeechKit HTTP traffic through the real
:class:`YandexSpeechKitProvider` + :func:`parseRecognitionEvents` parser so the
full submit -> poll -> getRecognition -> delete lifecycle and the real wire
framing flow through CI on every ``make test`` (no network, deterministic).

The tests fall into three groups:

1. **Sanity tests** that always run and only need ``input/scenarios.json``.
   They verify the scenario file is well-formed and points at the right
   runner class/method.

2. **Fixtures guard** — skips with a clear recording-instructions message when
   ``data/`` has no recorded fixtures (the default state on a fresh checkout).

3. **Replayer tests** parametrised over the JSON fixture files in ``data/``.
   When ``data/`` is empty, :func:`lib.aurumentation.findGoldenDataFiles`
   returns an empty list and pytest emits zero parametrised cases — so the
   suite stays green even before any fixture has been recorded.

**Self-contained replay (never touches the clip on disk).** The audio clips
under ``input/`` are committed TTS-generated synthetic samples, and the
``data/*.json`` fixtures are committed too. To keep replay self-contained and
format-agnostic, the replayer test RECOVERS the submitted audio bytes from the
committed fixture itself: the recorded ``recognizeFileAsync`` POST body carries
``content`` = ``base64(ExtractedAudio.data)``, which is NOT secret-masked (base64
cannot contain the literal API-key substring). :func:`_recoverAudioBytesFromFixture`
``base64.b64decode``\\ s that field and hands the bytes to
:meth:`~tests.lib.stt.golden.scenario_runner.YandexSTTScenarioRunner.runBytes`.

The replayer assertions require FINAL status and stable response-only segment
metadata: both committed fixtures are known mono speech recordings submitted
with speaker labeling enabled. Their final canonical envelope attribution tags
map to the generic ``attributionTag`` under the SPEAKER result role, so every
replay must produce at least one segment and preserve the recorded tag set.
This makes a parser regression that drops final envelopes or loses speaker
attribution fail rather than silently passing as NO_SPEECH. Specific
transcript-text assertions remain out of scope because the collector discards
the return value.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

import pytest

from lib.aurumentation import (
    GoldenDataScenarioDict,
    HttpCallDict,
    HttpRequestDict,
    findGoldenDataFiles,
    loadGoldenData,
)
from lib.aurumentation.replayer import GoldenDataReplayer
from lib.stt import STTAttributionType
from lib.stt.models import STTResultStatus
from tests.lib.stt.golden import GOLDEN_DATA_PATH
from tests.lib.stt.golden.scenario_runner import YandexSTTScenarioRunner

SCENARIOS_PATH: Path = Path(__file__).parent / "input" / "scenarios.json"

# Required scenario keys — kept in one place so the sanity test and the
# replayer test stay in agreement.
REQUIRED_SCENARIO_KEYS: Tuple[str, ...] = (
    "name",
    "description",
    "module",
    "class",
    "method",
    "init_kwargs",
    "kwargs",
)

REQUIRED_KWARGS_KEYS: Tuple[str, ...] = ("audioPath",)

# The committed mono SpeechKit recordings use these stable canonical envelope
# attribution tags. Keep assertions narrowly scoped to this response metadata,
# rather than transcript text or unrelated response details.
EXPECTED_ATTRIBUTION_TAGS: set[str] = {"0", "1"}

# The recorder's established placeholder. These assertions deliberately check
# fixture structure rather than individual captured values.
MASKED_VALUE: str = "***MASKED***"
CREDENTIAL_HEADER_NAMES: frozenset[str] = frozenset({"authorization", "x-folder-id"})
IDENTIFIER_HEADER_NAMES: frozenset[str] = frozenset({"x-client-request-id", "x-request-id", "x-server-trace-id"})
IDENTIFIER_FIELD_NAMES: frozenset[str] = frozenset({"id", "createdBy", "uuid", "userRequestId"})
CREDENTIAL_METADATA_FIELD_NAMES: frozenset[str] = frozenset({"apiKey", "folderId"})
STT_API_HOST: str = "stt.api.cloud.yandex.net"
OPERATION_API_HOST: str = "operation.api.cloud.yandex.net"
SUBMIT_PATH: str = "/stt/v3/recognizeFileAsync"
GET_RECOGNITION_PATH: str = "/stt/v3/getRecognition"
DELETE_RECOGNITION_PATH: str = "/stt/v3/deleteRecognition"
OPERATIONS_PATH_PREFIX: str = "/operations/"


def _getSpeechKitUrlPrivacyFailureCategory(url: str) -> Optional[str]:
    """Return a safe failure category when a URL is outside the recorded API surface.

    Args:
        url: Request URL from a golden fixture or a safe synthetic test value.

    Returns:
        ``None`` for an expected HTTPS SpeechKit lifecycle URL, otherwise a
        value-free structural failure category.
    """
    if any(character.isspace() or not character.isprintable() for character in url) or "#" in url:
        return "request URL structure"
    try:
        parsedUrl = urlsplit(url)
    except ValueError:
        return "request URL structure"

    if parsedUrl.scheme != "https" or not parsedUrl.netloc or parsedUrl.fragment:
        return "request URL structure"
    if parsedUrl.netloc == STT_API_HOST:
        if parsedUrl.path == SUBMIT_PATH:
            if "?" in url:
                return "submit URL structure"
            return None
        if parsedUrl.path not in {GET_RECOGNITION_PATH, DELETE_RECOGNITION_PATH}:
            return "STT endpoint structure"
        if not parsedUrl.query or any(not queryField for queryField in parsedUrl.query.split("&")):
            return "operation query structure"
        try:
            queryParameters: Dict[str, List[str]] = parse_qs(parsedUrl.query, keep_blank_values=True)
        except ValueError:
            return "request URL structure"
        if set(queryParameters) != {"operation_id"} or len(queryParameters["operation_id"]) != 1:
            return "operation query structure"
        return None
    if parsedUrl.netloc != OPERATION_API_HOST:
        return "request URL host"
    operationId: str = parsedUrl.path.removeprefix(OPERATIONS_PATH_PREFIX)
    if not parsedUrl.path.startswith(OPERATIONS_PATH_PREFIX) or not operationId or "/" in operationId or "?" in url:
        return "operation URL structure"
    return None


def _loadScenarios() -> List[Dict[str, Any]]:
    """Load and return the scenarios list from ``input/scenarios.json``.

    Returns:
        Parsed JSON content of the scenarios file.

    Raises:
        FileNotFoundError: When the scenarios file is missing.
        json.JSONDecodeError: When the file contains invalid JSON.
    """
    with SCENARIOS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _scenarioByName(name: str) -> Optional[Dict[str, Any]]:
    """Look up a scenario in ``input/scenarios.json`` by its ``name`` field.

    Args:
        name: Scenario name to find.

    Returns:
        Matching scenario dict, or ``None`` when not found.
    """
    for scenario in _loadScenarios():
        if scenario.get("name") == name:
            return scenario
    return None


def _discoverFixtures() -> List[str]:
    """Discover golden-data fixture files in ``data/``.

    Returns:
        Sorted list of absolute paths. Empty when no fixtures have been
        recorded yet — pytest will then emit zero parametrised cases for the
        replayer test, which is the desired no-op behaviour.
    """
    paths: List[str] = findGoldenDataFiles(GOLDEN_DATA_PATH)
    return sorted(paths)


def _loadResponseContentObjects(content: str, *, fixtureName: str) -> List[object]:
    """Parse a JSON response body that may use newline-delimited JSON frames.

    Args:
        content: Serialized response body from a golden fixture.
        fixtureName: Filename used only to identify a malformed fixture.

    Returns:
        Parsed JSON object or objects represented by the response body.
    """
    try:
        return [json.loads(content)]
    except json.JSONDecodeError:
        try:
            return [json.loads(line) for line in content.splitlines() if line]
        except json.JSONDecodeError:
            pytest.fail(f"{fixtureName}: privacy validation failed for response content structure", pytrace=False)
    return []


def _assertMaskedResponseIdentifiers(value: object, *, fixtureName: str) -> None:
    """Assert that identifier-bearing fields in a parsed response use the mask.

    Args:
        value: Parsed JSON value from a response body.
        fixtureName: Filename used only to identify a malformed fixture.

    Returns:
        None.
    """
    if isinstance(value, dict):
        for key, nestedValue in value.items():
            if not isinstance(key, str):
                pytest.fail(f"{fixtureName}: privacy validation failed for response structure", pytrace=False)
            if key in IDENTIFIER_FIELD_NAMES:
                if nestedValue != MASKED_VALUE:
                    pytest.fail(f"{fixtureName}: privacy validation failed for response identifiers", pytrace=False)
            _assertMaskedResponseIdentifiers(nestedValue, fixtureName=fixtureName)
    elif isinstance(value, list):
        for nestedValue in value:
            _assertMaskedResponseIdentifiers(nestedValue, fixtureName=fixtureName)


def _isMaskedOrPlaceholder(value: object) -> bool:
    """Return whether a metadata credential uses an approved non-secret form.

    Args:
        value: Metadata credential value to inspect.

    Returns:
        True when the value is the masking token or an environment placeholder.
    """
    return value == MASKED_VALUE or (isinstance(value, str) and value.startswith("${") and value.endswith("}"))


def _assertFixturePrivacy(fixturePath: str) -> None:
    """Assert structural privacy invariants for one committed STT fixture.

    Args:
        fixturePath: Absolute path to a committed fixture JSON file.

    Returns:
        None.
    """
    fixtureName: str = Path(fixturePath).name
    try:
        fixtureContent: object = json.loads(Path(fixturePath).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        pytest.fail(f"{fixtureName}: privacy validation failed for fixture structure", pytrace=False)
        return
    if not isinstance(fixtureContent, dict):
        pytest.fail(f"{fixtureName}: privacy validation failed for fixture structure", pytrace=False)
    metadata: object = fixtureContent.get("metadata")
    if not isinstance(metadata, dict):
        pytest.fail(f"{fixtureName}: privacy validation failed for metadata structure", pytrace=False)
    initKwargs: object = metadata.get("init_kwargs")
    if not isinstance(initKwargs, dict):
        pytest.fail(f"{fixtureName}: privacy validation failed for credential metadata structure", pytrace=False)
    for fieldName in CREDENTIAL_METADATA_FIELD_NAMES:
        if not _isMaskedOrPlaceholder(initKwargs.get(fieldName)):
            pytest.fail(f"{fixtureName}: privacy validation failed for credential metadata", pytrace=False)

    recordings: object = fixtureContent.get("recordings")
    if not isinstance(recordings, list):
        pytest.fail(f"{fixtureName}: privacy validation failed for recordings structure", pytrace=False)

    for recording in recordings:
        if not isinstance(recording, dict):
            pytest.fail(f"{fixtureName}: privacy validation failed for recording structure", pytrace=False)
        request: object = recording.get("request")
        response: object = recording.get("response")
        if not isinstance(request, dict):
            pytest.fail(f"{fixtureName}: privacy validation failed for request structure", pytrace=False)
        if not isinstance(response, dict):
            pytest.fail(f"{fixtureName}: privacy validation failed for response structure", pytrace=False)

        requestHeaders: object = request.get("headers")
        if not isinstance(requestHeaders, dict):
            pytest.fail(f"{fixtureName}: privacy validation failed for request header structure", pytrace=False)
        credentialHeaderNamesSeen: set[str] = set()
        for headerName, headerValue in requestHeaders.items():
            if not isinstance(headerName, str):
                pytest.fail(f"{fixtureName}: privacy validation failed for request header structure", pytrace=False)
            normalizedHeaderName: str = headerName.lower()
            if normalizedHeaderName in CREDENTIAL_HEADER_NAMES:
                if normalizedHeaderName in credentialHeaderNamesSeen or headerValue != MASKED_VALUE:
                    pytest.fail(
                        f"{fixtureName}: privacy validation failed for credential request headers", pytrace=False
                    )
                credentialHeaderNamesSeen.add(normalizedHeaderName)
            if normalizedHeaderName in IDENTIFIER_HEADER_NAMES:
                if not isinstance(headerValue, str) or headerValue not in {"", MASKED_VALUE}:
                    pytest.fail(f"{fixtureName}: privacy validation failed for request identifiers", pytrace=False)
        if credentialHeaderNamesSeen != CREDENTIAL_HEADER_NAMES:
            pytest.fail(f"{fixtureName}: privacy validation failed for credential request headers", pytrace=False)

        requestUrl: object = request.get("url")
        if not isinstance(requestUrl, str):
            pytest.fail(f"{fixtureName}: privacy validation failed for request URL structure", pytrace=False)
        urlFailureCategory: Optional[str] = _getSpeechKitUrlPrivacyFailureCategory(requestUrl)
        if urlFailureCategory is not None:
            pytest.fail(f"{fixtureName}: privacy validation failed for {urlFailureCategory}", pytrace=False)
        try:
            parsedUrl = urlsplit(requestUrl)
            queryParameters: Dict[str, List[str]] = parse_qs(parsedUrl.query, keep_blank_values=True)
        except ValueError:
            pytest.fail(f"{fixtureName}: privacy validation failed for request URL structure", pytrace=False)
            return
        if parsedUrl.netloc == OPERATION_API_HOST:
            if parsedUrl.path.removeprefix(OPERATIONS_PATH_PREFIX) != MASKED_VALUE:
                pytest.fail(f"{fixtureName}: privacy validation failed for operation URL", pytrace=False)
        if "operation_id" in queryParameters:
            if queryParameters["operation_id"] != [MASKED_VALUE]:
                pytest.fail(f"{fixtureName}: privacy validation failed for operation query", pytrace=False)

        requestParameters: object = request.get("params")
        if not isinstance(requestParameters, dict):
            pytest.fail(f"{fixtureName}: privacy validation failed for request parameter structure", pytrace=False)
        if "operation_id" in requestParameters:
            if requestParameters["operation_id"] != MASKED_VALUE:
                pytest.fail(f"{fixtureName}: privacy validation failed for operation parameters", pytrace=False)

        responseHeaders: object = response.get("headers")
        if not isinstance(responseHeaders, dict):
            pytest.fail(f"{fixtureName}: privacy validation failed for response header structure", pytrace=False)
        for headerName, headerValue in responseHeaders.items():
            if not isinstance(headerName, str):
                pytest.fail(f"{fixtureName}: privacy validation failed for response header structure", pytrace=False)
            if headerName.lower() in IDENTIFIER_HEADER_NAMES:
                if not isinstance(headerValue, str) or headerValue not in {"", MASKED_VALUE}:
                    pytest.fail(f"{fixtureName}: privacy validation failed for response identifiers", pytrace=False)

        responseContent: object = response.get("content")
        if not isinstance(responseContent, str):
            pytest.fail(f"{fixtureName}: privacy validation failed for response content structure", pytrace=False)
        for responseObject in _loadResponseContentObjects(responseContent, fixtureName=fixtureName):
            _assertMaskedResponseIdentifiers(responseObject, fixtureName=fixtureName)


def _resolveReplayInitKwargs(initKwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Replace ``${VAR}`` credential placeholders with dummy values for replay.

    During replay the recorded HTTP responses are matched by URL/body, not by
    headers, so the real API key is never needed. Any ``${...}`` value in
    ``init_kwargs`` (typically ``apiKey`` / ``folderId``) is replaced with a
    dummy non-empty string (the provider's constructor validation requires
    non-empty credentials). Non-placeholder values (e.g. ``language: "en-US"``)
    pass through unchanged.

    Args:
        initKwargs: The scenario's ``init_kwargs`` dict (from scenarios.json),
            which may contain ``${VAR}`` placeholders.

    Returns:
        A copy of ``init_kwargs`` with every ``${...}`` value replaced by a
        dummy non-empty string.
    """
    result: Dict[str, Any] = {}
    for key, value in initKwargs.items():
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            result[key] = f"replay-dummy-{key}"
        else:
            result[key] = value
    return result


#: The Yandex SpeechKit deferred-recognition submit endpoint path fragment. The
#: recorded POST to this URL is the one whose body carries the base64 audio.
_SUBMIT_URL_FRAGMENT: str = "recognizeFileAsync"


def _recoverAudioBytesFromFixture(fixture: GoldenDataScenarioDict) -> bytes:
    """Recover the submitted audio bytes from a committed fixture's submit recording.

    The recorded ``recognizeFileAsync`` POST request body is a JSON string whose
    ``content`` field is ``base64(ExtractedAudio.data)`` — the exact audio bytes
    that were submitted to Yandex (see
    :meth:`YandexSpeechKitProvider._buildSubmitBody`). The audio content is NOT
    secret-masked: :class:`~lib.aurumentation.masker.SecretMasker` only applies
    exact-substring replacement to request bodies, and base64 of audio bytes
    cannot contain the literal API-key substring. So the field survives intact
    in the committed fixture, and ``base64.b64decode`` recovers the bytes.

    This is what makes replay self-contained: replay never reads the
    ``input/*.ogg`` clip from disk, because the exact submitted bytes are
    embedded in the fixture.

    Args:
        fixture: A loaded golden-data fixture (the return of
            :func:`~lib.aurumentation.loadGoldenData`).

    Returns:
        The raw audio bytes that were submitted to Yandex (post-extraction —
        i.e. exactly what the provider sent as ``content``).

    Raises:
        ValueError: When the fixture has no ``recognizeFileAsync`` POST
            recording, the request body is missing, or the ``content`` field is
            absent/not a string.
    """
    recordings: List[HttpCallDict] = fixture["recordings"]
    for recording in recordings:
        request: HttpRequestDict = recording["request"]
        if request["method"] == "POST" and _SUBMIT_URL_FRAGMENT in request["url"]:
            bodyStr: Optional[str] = request.get("body")
            if bodyStr is None:
                raise ValueError(
                    "recognizeFileAsync POST recording has no request body — " "cannot recover audio bytes from fixture"
                )
            parsedBody: Dict[str, Any] = json.loads(bodyStr)
            contentField: object = parsedBody.get("content")
            if not isinstance(contentField, str) or not contentField:
                raise ValueError(
                    "recognizeFileAsync POST body has no non-empty 'content' string — "
                    "cannot recover audio bytes from fixture"
                )
            return base64.b64decode(contentField)
    raise ValueError(
        "No recognizeFileAsync POST recording found in fixture — "
        "cannot recover audio bytes. The fixture is malformed or was recorded "
        "with a non-standard submit flow."
    )


# ---------------------------------------------------------------------------
# Sanity tests — always runnable, no fixtures required.
# ---------------------------------------------------------------------------


def testScenariosFileIsValid() -> None:
    """``scenarios.json`` is loadable and every entry has the required fields.

    Verifies, for every scenario:

    * Top-level required keys are present.
    * ``module`` points at the STT scenario runner and ``class`` at the runner class.
    * ``method`` is ``run``.
    * ``kwargs`` contains ``audioPath``.
    * Names within the file are unique (so fixture filenames cannot clash).
    """
    assert SCENARIOS_PATH.exists(), f"scenarios.json not found at {SCENARIOS_PATH}"
    scenarios: List[Dict[str, Any]] = _loadScenarios()
    assert isinstance(scenarios, list), "scenarios.json must contain a JSON array"
    assert len(scenarios) >= 1, "scenarios.json must define at least one scenario"

    seenNames: set[str] = set()
    for index, scenario in enumerate(scenarios):
        path: str = f"scenarios[{index}]"
        for key in REQUIRED_SCENARIO_KEYS:
            assert key in scenario, f"{path}: missing required key '{key}'"

        name: str = scenario["name"]
        assert name not in seenNames, f"{path}: duplicate name '{name}'"
        seenNames.add(name)

        assert (
            scenario["module"] == "tests.lib.stt.golden.scenario_runner"
        ), f"{path}: 'module' must point at tests.lib.stt.golden.scenario_runner"
        assert scenario["class"] == "YandexSTTScenarioRunner", f"{path}: 'class' must be YandexSTTScenarioRunner"
        assert scenario["method"] == "run", f"{path}: 'method' must be run"

        kwargs: Dict[str, Any] = scenario["kwargs"]
        for key in REQUIRED_KWARGS_KEYS:
            assert key in kwargs, f"{path}: kwargs is missing '{key}'"
        assert (
            isinstance(kwargs["audioPath"], str) and kwargs["audioPath"]
        ), f"{path}: audioPath must be a non-empty string"


# ---------------------------------------------------------------------------
# Fixtures guard — explicit skip when no fixtures recorded.
# ---------------------------------------------------------------------------


def testGoldenFixturesAreRecorded() -> None:
    """Skip with a clear message when no golden fixtures have been recorded.

    This test exists so ``make test`` output shows an explicit 'skipped' entry
    with recording instructions, rather than the replayer test silently
    producing zero parametrised cases. Once fixtures exist, this test passes
    trivially and the parametrised replayer does the real work.
    """
    fixtures: List[str] = _discoverFixtures()
    if not fixtures:
        pytest.skip(
            "No golden STT fixtures found in data/. To record:\n"
            "  1. Set YANDEX_API_KEY and YANDEX_FOLDER_ID env vars (or .env file).\n"
            "  2. Provide short voice clips at input/sample_ru.ogg and input/sample_en.ogg\n"
            "     (any supported container — OGG_OPUS/MP3/WAV; replay is format-agnostic).\n"
            "  3. Run: ./venv/bin/python3 tests/lib/stt/golden/collect.py\n"
            "See tests/lib/stt/golden/README.md for the full workflow."
        )


def testSpeechKitUrlValidationRejectsUnexpectedShapes() -> None:
    """Require the privacy URL validator to accept only known SpeechKit routes.

    The strings here are synthetic structural examples. They deliberately do not
    originate from, or contain values from, a committed golden fixture.

    Returns:
        None.
    """
    validUrls: Tuple[str, ...] = (
        "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync",
        "https://operation.api.cloud.yandex.net/operations/***MASKED***",
        "https://stt.api.cloud.yandex.net/stt/v3/getRecognition?operation_id=***MASKED***",
        "https://stt.api.cloud.yandex.net/stt/v3/deleteRecognition?operation_id=***MASKED***",
    )
    invalidUrls: Tuple[str, ...] = (
        "stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync",
        "http://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync",
        "https://unexpected.example/stt/v3/recognizeFileAsync",
        "https:///stt/v3/recognizeFileAsync",
        "https://stt.api.cloud.yandex.net/stt/v3/unexpected",
        "https://operation.api.cloud.yandex.net/operations/",
        "https://operation.api.cloud.yandex.net/unexpected/***MASKED***",
        " https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync",
        "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync?",
        "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync#",
        "https://stt.api.cloud.yandex.net/stt/v3/getRecognition?&operation_id=***MASKED***",
        "https://stt.api.cloud.yandex.net/stt/v3/getRecognition?operation_id=***MASKED***&",
        "https://stt.api.cloud.yandex.net/stt/v3/getRecognition?operation_id=***MASKED***&&operation_id=***MASKED***",
        "https://stt.api.cloud.yandex.net/stt/v3/getRecognition?operation_id=***MASKED***\x7f",
        "https://stt.api.cloud.yandex.net/stt/v3/getRecognition?operation_id=***MASKED***\x80",
        "https://stt.api.cloud.yandex.net/stt/v3/getRecognition?operation_id=***MASKED***\u200b",
    )

    for url in validUrls:
        if _getSpeechKitUrlPrivacyFailureCategory(url) is not None:
            pytest.fail("safe synthetic URL was rejected", pytrace=False)
    for url in invalidUrls:
        if _getSpeechKitUrlPrivacyFailureCategory(url) is None:
            pytest.fail("unsafe synthetic URL was accepted", pytrace=False)


# ---------------------------------------------------------------------------
# Replayer tests — parametrised over recorded fixtures (may be empty).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixturePath", _discoverFixtures())
def testGoldenFixturePrivacy(fixturePath: str) -> None:
    """Require every committed STT fixture to use structural privacy masks.

    Args:
        fixturePath: Absolute path to a fixture JSON file in ``data/``.

    Returns:
        None.
    """
    _assertFixturePrivacy(fixturePath)


@pytest.mark.parametrize("fixturePath", _discoverFixtures())
async def testReplayTranscription(fixturePath: str) -> None:
    """Replay a known-speech Yandex STT lifecycle and require final tagged segments.

    For each recorded fixture this test:

    1. Loads the fixture (strict loader doubles as a well-formed-JSON check).
    2. Looks up the matching scenario in ``input/scenarios.json`` to recover the
       non-credential ``init_kwargs`` (the fixture stores ``${VAR}``
       placeholders, not resolved keys).
    3. RECOVERS the audio bytes from the committed fixture itself (the recorded
       ``recognizeFileAsync`` POST body's ``content`` field, base64-decoded) —
       NOT from the ``input/*.ogg`` clip on disk.
    4. Builds a :class:`YandexSTTScenarioRunner` with dummy credentials INSIDE
       the :class:`GoldenDataReplayer` context (so the provider's
       ``httpx.AsyncClient`` is auto-intercepted by the replay transport).
    5. Runs the recovered bytes through :meth:`runBytes` — the full extract +
       submit + poll + getRecognition + parse + delete path. Because the
       recovered bytes are the post-extraction bytes (what was actually
       submitted), :func:`extractAudio` re-probes them as a supported container
       and passes them through verbatim, so the re-submitted body is
       byte-identical to the recording (format-agnostic replay).
    6. Requires the :class:`TranscriptionResult` status to be FINAL. Both
        committed fixtures are known speech recordings, so NO_SPEECH would mean
        a parser regression dropped their final envelopes. Requires at least one
         segment, the recorded generic attribution tags, and a SPEAKER role.

    Args:
        fixturePath: Absolute path to a fixture JSON file in ``data/``.
    """
    # The aurumentation loader is strict and will raise on a malformed file,
    # so this single call doubles as the "well-formed JSON" check.
    fixture = loadGoldenData(fixturePath)
    # ``loadGoldenData`` types metadata as a TypedDict but in practice it
    # carries arbitrary fields written by the collector. Cast to a plain dict
    # so ``.get(...)`` on those fields is type-safe.
    metadata: Dict[str, Any] = dict(fixture["metadata"])

    scenarioName: str = metadata.get("name", "")
    scenario: Optional[Dict[str, Any]] = _scenarioByName(scenarioName)
    assert scenario is not None, (
        f"Fixture '{Path(fixturePath).name}' has name '{scenarioName}' which is not present "
        "in input/scenarios.json. Either re-record after editing scenarios.json or "
        "update the scenario list."
    )

    # Build replay init_kwargs: replace credential placeholders with dummies.
    # Non-credential fields (e.g. language) pass through unchanged.
    replayInitKwargs: Dict[str, Any] = _resolveReplayInitKwargs(scenario["init_kwargs"])

    # Recover the audio bytes from the committed fixture itself (NOT from the
    # input/*.ogg clip on disk — keeps replay self-contained and
    # format-agnostic). The recorded recognizeFileAsync POST body carries
    # content=base64(audio.data), which is not secret-masked — see
    # _recoverAudioBytesFromFixture.
    audioBytes: bytes = _recoverAudioBytesFromFixture(fixture)

    # Construct the runner INSIDE the replayer context so the provider's
    # httpx.AsyncClient (built in __init__) gets the ReplayTransport.
    async with GoldenDataReplayer(fixture):
        runner: YandexSTTScenarioRunner = YandexSTTScenarioRunner(**replayInitKwargs)
        result = await runner.runBytes(data=audioBytes)

    # Both committed fixtures are known speech recordings. FINAL plus non-empty
    # tagged segments proves the parser retained their committed final envelopes.
    assert result.status is STTResultStatus.FINAL, (
        f"Replay produced {result.status!r} ({result.errorCode}) for known-speech scenario '{scenarioName}'. "
        "This indicates the parser failed to retain the committed final envelope. "
        f"Fixture: {fixturePath}"
    )
    assert len(result.segments) > 0, (
        f"FINAL status for scenario '{scenarioName}' but segments is empty — "
        "unexpected for a known speech recording."
    )
    assert {segment.attributionTag for segment in result.segments} == EXPECTED_ATTRIBUTION_TAGS, (
        f"Unexpected per-segment attribution tags for scenario '{scenarioName}'. "
        f"The committed recognition response uses the stable attribution tags {EXPECTED_ATTRIBUTION_TAGS}."
    )
    assert result.attributionType is STTAttributionType.SPEAKER

    # Always-on cheap check: at least one HTTP recording was captured.
    assert isinstance(fixture["recordings"], list)
    assert len(fixture["recordings"]) > 0, (
        f"Fixture '{Path(fixturePath).name}' contains zero HTTP recordings — "
        "the collector did not capture any traffic."
    )
