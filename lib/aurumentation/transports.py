"""Custom httpx transports for recording and replaying HTTP traffic.

This module implements custom httpx transports that can intercept HTTP
recordings for recording or replay previously recorded recordings.
"""

from datetime import datetime
from typing import List, Optional

import httpx

from .types import HttpCall, HttpRequest, HttpResponse


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
        self.recordings: List[HttpCall] = []

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
        request_data = HttpRequest(
            method=request.method,
            url=str(request.url),
            headers=dict(request.headers),
            params=dict(request.url.params),
            body=request.content.decode() if request.content else None,
        )

        # Make actual HTTP call
        response = await self.wrapped.handle_async_request(request)

        # Read the response content if it hasn't been read yet
        if not hasattr(response, "_content"):
            await response.aread()

        # Capture response details
        response_data = HttpResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            content=response.content.decode() if response.content else "",
        )

        # Store recording with timestamp
        call = HttpCall(request=request_data, response=response_data, timestamp=datetime.utcnow())
        self.recordings.append(call)
        print(f"RecordingTransport: Recorded call to {request.url}, now have {len(self.recordings)} recordings")

        return response


class ReplayTransport(httpx.AsyncHTTPTransport):
    """Custom httpx transport that replays recorded HTTP traffic.

    This transport takes a list of recorded HttpCall objects and matches
    incoming requests to recorded recordings, returning recorded responses
    without making real HTTP recordings.
    """

    def __init__(self, recordings: List[HttpCall], *args, **kwargs):
        """Initialize the replay transport.

        Args:
            recordings: List of recorded HttpCall objects to replay.
            *args: Additional arguments passed to the parent class.
            **kwargs: Additional keyword arguments passed to the parent class.
        """
        super().__init__(*args, **kwargs)
        self.recordings = recordings
        self.call_index = 0

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

        # Find matching call
        for call in self.recordings:
            # Match by method and URL
            if call.request.method == method and call.request.url == url:
                # Create response from recorded data
                response = httpx.Response(
                    status_code=call.response.status_code,
                    headers=call.response.headers,
                    content=call.response.content.encode() if call.response.content else b"",
                )
                return response

        # No matching call found
        raise ValueError(f"No recorded call found for {method} {url}")
