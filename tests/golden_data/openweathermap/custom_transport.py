"""Custom transport for matching OpenWeatherMap API requests with golden data."""

from typing import List
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from lib.aurumentation.types import HttpCallDict


class OpenWeatherMapReplayTransport(httpx.AsyncHTTPTransport):
    """Custom transport that matches OpenWeatherMap API requests with golden data.

    This transport handles the special case where API keys in requests may differ
    from those in the golden data recordings.
    """

    def __init__(self, recordings: List[HttpCallDict], *args, **kwargs):
        """Initialize the transport with recordings.

        Args:
            recordings: List of recorded HttpCallDict objects to replay.
            *args: Additional arguments passed to the parent class.
            **kwargs: Additional keyword arguments passed to the parent class.
        """
        super().__init__(*args, **kwargs)
        self.recordings = recordings

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

        # Normalize URL by masking API key
        normalized_url = self._normalize_url(url)

        # Find matching call
        for call in self.recordings:
            # Normalize recorded URL
            recorded_url = call["request"]["url"]
            normalized_recorded_url = self._normalize_url(recorded_url)

            # Match by method and normalized URL
            if call["request"]["method"] == method and normalized_url == normalized_recorded_url:
                # Create response from recorded data
                response = httpx.Response(
                    status_code=call["response"]["status_code"],
                    headers=call["response"]["headers"],
                    content=call["response"]["content"].encode() if call["response"]["content"] else b"",
                )
                return response

        # No matching call found
        raise ValueError(f"No recorded call found for {method} {url}")

    def _normalize_url(self, url: str) -> str:
        """Normalize URL by masking API key parameter.

        Args:
            url: URL to normalize

        Returns:
            Normalized URL with API key masked
        """
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)

        # Mask API key if present
        if "appid" in query_params:
            query_params["appid"] = ["***MASKED***"]

        # Reconstruct URL
        normalized_query = urlencode(query_params, doseq=True)
        normalized_url = urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, normalized_query, parsed.fragment)
        )

        return normalized_url
