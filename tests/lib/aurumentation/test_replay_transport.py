"""Regression tests for :class:`lib.aurumentation.transports.ReplayTransport`.

These tests lock in the replay semantics for repeated identical requests. The
original ``ReplayTransport`` was first-match-wins with no advancing (the
``call_index`` field was dead code): two recordings sharing a request signature
made the second unreachable, so a replay of a polling lifecycle — which records
several responses to the SAME URL (e.g. ``done:false`` → ``done:true`` polls) —
returned the first poll response forever and spun until its operation budget
timed out (looked like a hang). See ``docs/llm/aurumentation.md`` §8.

The fix advances through matched recordings in record order on successive calls
for the same request signature, while leaving single-match requests on their one
recording (backward-compatible with every existing golden suite, all of which
record each request signature at most once).

These tests exercise the transport directly via ``httpx.AsyncClient(transport=...)``
(no global patch needed), so they are fast, deterministic, and version-independent.
"""

from typing import List, Optional

import httpx
import pytest

from lib.aurumentation.transports import ReplayTransport
from lib.aurumentation.types import HttpCallDict, HttpRequestDict, HttpResponseDict


def _makeRecording(method: str, url: str, *, body: Optional[str] = None, responseContent: str) -> HttpCallDict:
    """Build a minimal :class:`HttpCallDict` for replay-matching tests.

    Constructs a recording mirroring the on-disk fixture shape: ``body=None``
    for body-less methods (GET/DELETE — matching the real fixtures, which store
    ``null``, and matching the incoming request whose content is ``None``) or the
    given body for body-bearing methods (POST/PUT). Params default to empty (the
    request signature is method + URL + params + body). Headers are not part of
    replay matching and are left empty.

    Args:
        method: HTTP method (GET, POST, ...).
        url: Full request URL.
        body: Request body string, or ``None`` (the default) for body-less
            requests. Must be ``None`` for GET/DELETE so the recorded body
            matches the incoming request's ``None`` body byte-for-byte.
        responseContent: The recorded response body to return on match.

    Returns:
        HttpCallDict: A complete recording usable as a ``recordings`` list entry.
    """
    request: HttpRequestDict = {
        "method": method,
        "url": url,
        "headers": {},
        "params": {},
        "body": body,
    }
    response: HttpResponseDict = {
        "status_code": 200,
        "headers": {"content-type": "application/json"},
        "content": responseContent,
    }
    return {"request": request, "response": response, "timestamp": "2024-01-01T00:00:00+00:00"}


async def _get(client: httpx.AsyncClient, url: str) -> str:
    """Issue a GET via ``client`` and return the decoded response text.

    Args:
        client: An httpx AsyncClient configured with a ReplayTransport.
        url: The URL to GET.

    Returns:
        The response body text.
    """
    response = await client.get(url)
    return response.text


async def testReplayAdvancesThroughIdenticalRequestSignatures() -> None:
    """Successive identical requests return matched recordings in record order.

    This is the core regression for the polling-lifecycle hang: a replay of N
    responses to the SAME (method, URL, params, body) must return recording 0,
    then recording 1, ..., not recording 0 forever. With the old first-match
    behaviour, calls 1 and 2 below both returned ``"a"`` and ``"c"`` was
    unreachable — which is exactly what kept the STT poll loop observing
    ``done:false`` on every iteration.
    """
    url = "https://example.test/operations/op1"
    recordings: List[HttpCallDict] = [
        _makeRecording("GET", url, responseContent="a"),
        _makeRecording("GET", url, responseContent="b"),
        _makeRecording("GET", url, responseContent="c"),
    ]
    transport = ReplayTransport(recordings=recordings)
    async with httpx.AsyncClient(transport=transport) as client:
        assert await _get(client, url) == "a"
        assert await _get(client, url) == "b"
        assert await _get(client, url) == "c"


async def testReplayExhaustedSequenceRaises() -> None:
    """When more requests are issued than were recorded, ValueError is raised.

    In a correct replay the consumer stops at the terminal recorded response
    (e.g. ``done:true``), so exhausting a multi-match sequence means the
    consumer is over-polling — a regression a shared replay library must surface
    loudly. Under the previous silent-clamp behaviour the extra request below
    returned the last recording (``'{"done": true}'``) with no failure, masking
    the bug. Now the third request raises instead of clamping.
    """
    url = "https://example.test/operations/op2"
    recordings: List[HttpCallDict] = [
        _makeRecording("GET", url, responseContent='{"done": false}'),
        _makeRecording("GET", url, responseContent='{"done": true}'),
    ]
    transport = ReplayTransport(recordings=recordings)
    async with httpx.AsyncClient(transport=transport) as client:
        assert await _get(client, url) == '{"done": false}'
        assert await _get(client, url) == '{"done": true}'
        # Past the end of the recorded sequence — raises, does not clamp.
        with pytest.raises(ValueError, match="Replay exhausted"):
            await _get(client, url)


async def testReplaySingleMatchResolvesThenRaisesOnRepeat() -> None:
    """A single-match request signature resolves to its one recording; a repeat raises.

    Backward-compatibility guarantee for the five existing golden suites
    (openweathermap, yandex_search, geocode_maps, ai, divination): every one of
    them records a request signature at most once AND issues it exactly once, so
    the first request resolves to that recording (index 0, no advancing). A
    repeat is an over-polling regression and raises just like a multi-match
    sequence does — the raise-on-exhaustion contract is uniform across single-
    and multi-match signatures (exhaustion does not special-case a count of 1).
    """
    url = "https://example.test/single"
    recordings: List[HttpCallDict] = [
        _makeRecording("GET", url, responseContent="only"),
    ]
    transport = ReplayTransport(recordings=recordings)
    async with httpx.AsyncClient(transport=transport) as client:
        # First request resolves to the one recording — backward-compatible.
        assert await _get(client, url) == "only"
        # A repeat is over-polling; raises uniformly with multi-match exhaustion.
        with pytest.raises(ValueError, match="Replay exhausted"):
            await _get(client, url)


async def testReplayDistinctRequestSignaturesAdvanceIndependently() -> None:
    """Requests matching DIFFERENT recording sets advance on independent cursors.

    Two requests to the same URL but with different bodies match different
    recording sets, so each must advance through its own matches without
    interfering with the other. (The cursor is keyed by the matched-indices
    tuple, not by URL alone.) Also covers interleaved ordering: a recording set
    need not be contiguous in the recordings list.
    """
    url = "https://example.test/op"
    recordings: List[HttpCallDict] = [
        _makeRecording("POST", url, body="A", responseContent="a0"),
        _makeRecording("POST", url, body="B", responseContent="b0"),
        _makeRecording("POST", url, body="A", responseContent="a1"),
        _makeRecording("POST", url, body="B", responseContent="b1"),
    ]
    transport = ReplayTransport(recordings=recordings)
    async with httpx.AsyncClient(transport=transport) as client:
        # Body A advances through its own matches (recordings 0 and 2).
        assert (await client.post(url, content="A")).text == "a0"
        assert (await client.post(url, content="A")).text == "a1"
        # Body B is unaffected by A's cursor and advances through 1 and 3.
        assert (await client.post(url, content="B")).text == "b0"
        assert (await client.post(url, content="B")).text == "b1"


async def testReplayNoMatchRaises() -> None:
    """An incoming request with no matching recording raises ValueError.

    Preserves the original no-match contract: advancing through duplicates does
    not change behaviour for genuinely unmatched requests.
    """
    recordings: List[HttpCallDict] = [
        _makeRecording("GET", "https://example.test/known", responseContent="ok"),
    ]
    transport = ReplayTransport(recordings=recordings)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match="No recorded call found"):
            await client.get("https://example.test/unknown")
