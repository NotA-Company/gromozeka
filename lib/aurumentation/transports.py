"""Custom httpx transports for recording and replaying HTTP traffic.

This module implements custom httpx transports that can intercept HTTP
requests for recording or replay previously recorded requests.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from .types import HttpCallDict, HttpRequestDict, HttpResponseDict

logger = logging.getLogger(__name__)


class RecordingTransport(httpx.AsyncHTTPTransport):
    """Custom httpx transport that records all HTTP traffic.

    This transport wraps a real httpx transport and intercepts all HTTP requests,
    recording the request and response details before passing through to the
    real transport for actual HTTP requests.

    Attributes:
        wrapped: The underlying httpx.AsyncHTTPTransport that handles actual HTTP requests.
        recordings: List of recorded HTTP calls, each containing request, response, and timestamp.
    """

    def __init__(self, wrapped: Optional[httpx.AsyncHTTPTransport] = None, *args, **kwargs) -> None:
        """Initialize the recording transport.

        Args:
            wrapped: The real transport to wrap. If None, creates a default AsyncHTTPTransport.
            *args: Additional arguments passed to the parent class.
            **kwargs: Additional keyword arguments passed to the parent class.
        """
        super().__init__(*args, **kwargs)
        self.wrapped = wrapped or httpx.AsyncHTTPTransport(*args, **kwargs)
        self.recordings: List[HttpCallDict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Intercept, record, and forward an HTTP request.

        Args:
            request: The httpx Request to process.

        Returns:
            The httpx Response from the real transport.
        """
        # Debug logging of the outgoing call
        logger.debug("Recording HTTP call: %s %s", request.method, request.url)

        # Capture request details
        request_data: HttpRequestDict = {
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "params": dict(request.url.params),
            "body": request.content.decode() if request.content else None,
        }

        # Make actual HTTP call
        response = await self.wrapped.handle_async_request(request)

        # Read the response content if it hasn't been read yet
        if not hasattr(response, "_content"):
            await response.aread()

        # Capture response details
        response_data: HttpResponseDict = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content": response.content.decode() if response.content else "",
        }

        # Store recording with timestamp
        call: HttpCallDict = {
            "request": request_data,
            "response": response_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.recordings.append(call)
        logger.debug(
            "RecordingTransport: Recorded call to %s, now have %d recordings",
            request.url,
            len(self.recordings),
        )

        return response


class ReplayTransport(httpx.AsyncHTTPTransport):
    """Custom httpx transport that replays recorded HTTP traffic.

    This transport takes a list of recorded HttpCallDict objects and matches
    incoming requests to recorded requests, returning recorded responses
    without making real HTTP requests.

    Attributes:
        recordings: List of recorded HttpCallDict objects to replay.
        _matchCursors: Per-request-signature advancing cursor (see handle_async_request).

    Note:
        The transport assumes sequential request issuance per signature; the
        read-increment-write on ``_matchCursors`` is not concurrency-safe. For
        concurrent consumers, use an ``asyncio.Lock`` per matchKey.
    """

    def __init__(self, recordings: List[HttpCallDict], *args, **kwargs) -> None:
        """Initialize the replay transport.

        Args:
            recordings: List of recorded HttpCallDict objects to replay.
            *args: Additional arguments passed to the parent class.
            **kwargs: Additional keyword arguments passed to the parent class.
        """
        super().__init__(*args, **kwargs)
        self.recordings = recordings
        # Per-request-signature advancing cursor, keyed by the tuple of recording
        # indices that match a given incoming request. Identical requests share
        # a cursor and advance through their matched recordings in record order
        # on successive calls (see handle_async_request). This lets a replay
        # model a sequence of identical-URL responses — e.g. a polling lifecycle
        # whose done:false / done:true responses share a URL — instead of
        # forever returning the first match. Single-match signatures are
        # unaffected (their cursor never advances past the one recording).
        self._matchCursors: Dict[Tuple[int, ...], int] = {}

    def _urlsMatch(self, recorded_url: str, request_url: str) -> bool:
        """Check if two URLs match, handling masked API keys.

        Args:
            recorded_url: The URL from the recorded data (may have masked API key).
            request_url: The URL from the current request.

        Returns:
            True if the URLs match, False otherwise.
        """
        # If the recorded URL doesn't have a masked API key, do exact match
        if "***MASKED***" not in recorded_url:
            return recorded_url == request_url

        # If the recorded URL has a masked API key, do pattern matching
        # Replace the masked API key with a regex pattern. The first replace
        # consumes every "***MASKED***" occurrence (re.escape makes the literal
        # "\*\*\*MASKED\*\*\*"), so there is nothing left for a second pass.
        pattern = re.escape(recorded_url).replace(r"\*\*\*MASKED\*\*\*", r"[^&]*")

        # Match the pattern against the request URL
        return bool(re.match(pattern, request_url))

    def _paramsMatch(self, recorded_params: dict, request_params: dict) -> bool:
        """Check if two parameter dictionaries match, handling masked API keys.

        Args:
            recorded_params: Parameters from the recorded data (may have masked API key).
            request_params: Parameters from the current request.

        Returns:
            True if the parameters match, False otherwise.
        """
        # If the recorded params don't have a masked API key, do exact match
        if "appid" in recorded_params and "***MASKED***" not in recorded_params["appid"]:
            return recorded_params == request_params

        # Create a copy of the recorded params
        recorded_params_copy = recorded_params.copy()

        # If the recorded appid is masked, match any appid in the request
        if "appid" in recorded_params_copy and "***MASKED***" in recorded_params_copy["appid"]:
            # Remove appid from both for comparison
            recorded_params_no_appid = {k: v for k, v in recorded_params_copy.items() if k != "appid"}
            request_params_no_appid = {k: v for k, v in request_params.items() if k != "appid"}
            return recorded_params_no_appid == request_params_no_appid

        # Otherwise do exact match
        return recorded_params_copy == request_params

    def _bodyMatch(self, recorded_body: Optional[str], request_body: Optional[str]) -> bool:
        """Check if two request bodies match, handling masked values.

        Note:
            Body comparison is byte-exact — if httpx's JSON serialization
            changes, regenerate fixtures.

        Args:
            recorded_body: Body from the recorded data (may have masked values).
            request_body: Body from the current request.

        Returns:
            True if the bodies match, False otherwise.
        """
        # If either body is None, they must both be None to match
        if recorded_body is None or request_body is None:
            return recorded_body == request_body

        # If the recorded body doesn't have masked values, do exact match
        if "***MASKED***" not in recorded_body:
            return recorded_body == request_body

        # If the recorded body has masked values, do pattern matching
        # Replace the masked values with a regex pattern
        pattern = re.escape(recorded_body).replace(r"\*\*\*MASKED\*\*\*", r"[^&]*")

        # Match the pattern against the request body
        return bool(re.match(pattern, request_body))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Return a recorded response for a matching request, advancing through duplicates.

        Collects EVERY recording matching the incoming request (by method, URL,
        params, body, with ``***MASKED***`` wildcards) and returns them in
        record-order on successive calls for the same request signature. This
        lets a replay model a sequence of identical-URL responses — e.g. a
        polling lifecycle whose ``done:false`` → ``done:true`` responses share a
        URL — instead of forever returning the first one (which left the second
        recording unreachable and caused polling replays to spin until their
        budget timed out).

        Single-match requests (the common case: one recording per request
        signature) always resolve to their one recording, so this is
        backward-compatible with the previous first-match behaviour for every
        existing golden suite. When a multi-match sequence is exhausted (more
        requests issued than were recorded), ValueError is raised rather than
        silently clamping — in a correct replay the consumer stops at the
        terminal recorded response (e.g. a ``done:true`` poll), so the only way
        to exhaust the sequence is an over-polling regression, which a shared
        regression-catching library must surface loudly (verifyAllCallsUsed is
        a stub, so this raise is the over-polling signal).

        Note:
            Matching is a linear scan over ALL recordings on every request —
            O(n) in the fixture count, plus a tuple allocation for the match
            key. This is acceptable for current fixture sizes; if fixture
            counts grow large, precompute a ``Dict[signature, Tuple[int, ...]]``
            in ``__init__`` to cache per-signature match indices.

        Args:
            request: The httpx Request to match.

        Returns:
            An httpx Response created from recorded data.

        Raises:
            ValueError: If no matching recorded call is found, OR if the
                per-signature advancing cursor is exhausted (more requests issued
                for this signature than were recorded — the over-polling signal).
        """
        # Normalize the request for matching.
        method = request.method
        url = str(request.url)
        params = dict(request.url.params)
        body = request.content.decode() if request.content else None

        # Collect EVERY recording matching this request signature. When a
        # lifecycle records several responses to the SAME (method, URL, params,
        # body) — e.g. a polling loop — there will be more than one.
        matchingIndices: List[int] = [
            index
            for index, call in enumerate(self.recordings)
            if (
                call["request"]["method"] == method
                and self._urlsMatch(call["request"]["url"], url)
                and self._paramsMatch(call["request"].get("params", {}), params)
                and self._bodyMatch(call["request"].get("body"), body)
            )
        ]
        if not matchingIndices:
            raise ValueError(f"No recorded call found for {method} {url} {params} {body}")

        # Advance through matched recordings in record order on successive calls
        # for the SAME request signature. The cursor is keyed by the tuple of
        # matched recording indices, so requests matching DIFFERENT recording
        # sets (e.g. same URL but different body) advance independently. For a
        # single-match signature the cursor has no observable effect: index 0 is
        # always returned.
        matchKey: Tuple[int, ...] = tuple(matchingIndices)
        cursor: int = self._matchCursors.get(matchKey, 0)
        if cursor >= len(matchingIndices):
            # Exhausted the recorded sequence for this signature — the consumer
            # issued more requests than were recorded. Raise loudly: in a correct
            # replay the consumer stops at the terminal recorded response, so
            # exhaustion is an over-polling regression (verifyAllCallsUsed is a
            # stub, so this raise is the only signal). See docstring.
            raise ValueError(
                f"Replay exhausted for {method} {url}: {cursor + 1} requests issued "
                f"for this signature but only {len(matchingIndices)} recording(s) "
                f"matched. Likely an over-polling regression; if the extra request "
                f"is legitimate, record one more response."
            )
        chosenIndex: int = matchingIndices[cursor]
        self._matchCursors[matchKey] = cursor + 1

        # Create response from the chosen recording.
        call: HttpCallDict = self.recordings[chosenIndex]
        response = httpx.Response(
            status_code=call["response"]["status_code"],
            headers=call["response"]["headers"],
            content=call["response"]["content"].encode() if call["response"]["content"] else b"",
        )
        return response
