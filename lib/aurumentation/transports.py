"""Custom httpx transports for recording and replaying HTTP traffic.

This module implements custom httpx transports that can intercept HTTP
recordings for recording or replay previously recorded recordings.
"""

import re
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from .types import HttpCallDict, HttpRequestDict, HttpResponseDict


class RecordingTransport(httpx.AsyncHTTPTransport):
    """Custom httpx transport that records all HTTP traffic.

    This transport wraps a real httpx transport and intercepts all HTTP recordings,
    recording the request and response details before passing through to the
    real transport for actual HTTP recordings.
    """

    def __init__(self, wrapped: Optional[httpx.AsyncHTTPTransport] = None, *args, **kwargs):
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
        # Print debug info
        print(f"Recording HTTP call: {request.method} {request.url}")

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
        print(f"RecordingTransport: Recorded call to {request.url}, now have {len(self.recordings)} recordings")

        return response


class ReplayTransport(httpx.AsyncHTTPTransport):
    """Custom httpx transport that replays recorded HTTP traffic.

    This transport takes a list of recorded HttpCallDict objects and matches
    incoming requests to recorded recordings, returning recorded responses
    without making real HTTP recordings.
    """

    def __init__(self, recordings: List[HttpCallDict], *args, **kwargs):
        """Initialize the replay transport.

        Args:
            recordings: List of recorded HttpCallDict objects to replay.
            *args: Additional arguments passed to the parent class.
            **kwargs: Additional keyword arguments passed to the parent class.
        """
        super().__init__(*args, **kwargs)
        self.recordings = recordings
        self.call_index = 0

    def _urlsMatch(self, recorded_url: str, request_url: str) -> bool:
        """Check if two URLs match, handling masked API keys.

        Args:
            recorded_url: The URL from the recorded data (may have masked API key)
            request_url: The URL from the current request

        Returns:
            True if the URLs match, False otherwise
        """
        # If the recorded URL doesn't have a masked API key, do exact match
        if "***MASKED***" not in recorded_url:
            return recorded_url == request_url

        # If the recorded URL has a masked API key, do pattern matching
        # Replace the masked API key with a regex pattern
        pattern = re.escape(recorded_url).replace(r"\*\*\*MASKED\*\*\*", r"[^&]*")

        # Also handle URL-encoded masked key
        pattern = pattern.replace(r"\*\*\*MASKED\*\*\*", r"[^&]*")

        # Match the pattern against the request URL
        return bool(re.match(pattern, request_url))

    def _paramsMatch(self, recorded_params: dict, request_params: dict) -> bool:
        """Check if two parameter dictionaries match, handling masked API keys.

        Args:
            recorded_params: Parameters from the recorded data (may have masked API key)
            request_params: Parameters from the current request

        Returns:
            True if the parameters match, False otherwise
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

        Args:
            recorded_body: Body from the recorded data (may have masked values)
            request_body: Body from the current request

        Returns:
            True if the bodies match, False otherwise
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
        """Return a recorded response for a matching request.

        Args:
            request: The httpx Request to match.

        Returns:
            An httpx Response created from recorded data.

        Raises:
            ValueError: If no matching recorded call is found.
        """
        # Normalize the request for matching
        method = request.method
        url = str(request.url)
        params = dict(request.url.params)
        body = request.content.decode() if request.content else None

        # Find matching call
        for call in self.recordings:
            # Match by method, URL, params, and body
            if (
                call["request"]["method"] == method
                and self._urlsMatch(call["request"]["url"], url)
                and self._paramsMatch(call["request"].get("params", {}), params)
                and self._bodyMatch(call["request"].get("body"), body)
            ):
                # Create response from recorded data
                response = httpx.Response(
                    status_code=call["response"]["status_code"],
                    headers=call["response"]["headers"],
                    content=call["response"]["content"].encode() if call["response"]["content"] else b"",
                )
                return response

        # No matching call found
        raise ValueError(f"No recorded call found for {method} {url} {params} {body}")
