"""Tests for MaxBotClient basePollingUrl / localReceiverToken support.

Covers the routing logic added to :meth:`MaxBotClient.getUpdates`:

* When ``basePollingUrl`` is unset, polling must go through the normal Max API
  path (``self.get("/updates", ...)``) and never touch the local receiver.
* When ``basePollingUrl`` is set, polling must route to
  :meth:`MaxBotClient._makeLocalRequest` and never call ``self.get``.
* :meth:`MaxBotClient._makeLocalRequest` sends an ``Authorization`` header
  holding ``localReceiverToken`` when one is configured, and omits it entirely
  otherwise (so the bot access token is never leaked to the local receiver).
* The trailing slash on ``basePollingUrl`` is stripped at construction time so
  the assembled local URL has no accidental double slash.

httpx is patched so no real network I/O happens.
"""

from typing import Any, Dict
from unittest.mock import AsyncMock, patch

from lib.max_bot.client import MaxBotClient

# Shape returned by /updates when there is nothing to poll. Usable both as a
# raw dict (for the method-level mocks) and as a JSON payload (for _FakeResponse).
_EMPTY_UPDATES_RESPONSE: Dict[str, Any] = {"updates": [], "marker": None}


class _FakeResponse:
    """Minimal stand-in for :class:`httpx.Response` used by local-receiver tests.

    Only the surface area touched by :meth:`MaxBotClient._makeLocalRequest`
    (``status_code``, ``text``, ``json()``) is implemented.

    Attributes:
        _payload: JSON payload returned by :meth:`json`.
        status_code: HTTP status code reported by the fake response.
        text: Body text (used only in the error-path log message).
    """

    def __init__(self, payload: Dict[str, Any], status_code: int = 200) -> None:
        """Initialise the fake response.

        Args:
            payload: JSON payload to return from :meth:`json`.
            status_code: HTTP status code to report. Defaults to 200.

        Returns:
            None
        """
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self) -> Dict[str, Any]:
        """Return the canned JSON payload.

        Returns:
            The payload dict supplied at construction.
        """
        return self._payload


class TestMaxBotClientBasePollingUrl:
    """Tests for basePollingUrl routing and localReceiverToken auth in MaxBotClient."""

    async def test_noBasePollingUrl_usesDefaultApi(self) -> None:
        """getUpdates routes to self.get when basePollingUrl is unset.

        Ensures the local-receiver path is never taken when no
        ``basePollingUrl`` was supplied, and that the request lands on
        ``self.get("/updates", ...)`` with the expected query params.

        Args:
            None

        Returns:
            None
        """
        client = MaxBotClient("test-token")

        with (
            patch.object(MaxBotClient, "get", new=AsyncMock(return_value=_EMPTY_UPDATES_RESPONSE)) as mockGet,
            patch.object(
                MaxBotClient, "_makeLocalRequest", new=AsyncMock(return_value=_EMPTY_UPDATES_RESPONSE)
            ) as mockLocal,
        ):
            await client.getUpdates()

        assert mockGet.called
        assert "/updates" in mockGet.call_args.args
        assert "params" in mockGet.call_args.kwargs
        assert not mockLocal.called

    async def test_withBasePollingUrl_usesLocalRequest(self) -> None:
        """getUpdates routes to _makeLocalRequest when basePollingUrl is set.

        Ensures the local-receiver path is taken and the normal Max API path
        (``self.get``) is never reached when a ``basePollingUrl`` is configured.

        Args:
            None

        Returns:
            None
        """
        client = MaxBotClient("test-token", basePollingUrl="http://127.0.0.1:8443")

        with (
            patch.object(
                MaxBotClient, "_makeLocalRequest", new=AsyncMock(return_value=_EMPTY_UPDATES_RESPONSE)
            ) as mockLocal,
            patch.object(MaxBotClient, "get", new=AsyncMock(return_value=_EMPTY_UPDATES_RESPONSE)) as mockGet,
        ):
            await client.getUpdates()

        assert mockLocal.called
        assert "/updates" in mockLocal.call_args.args
        assert "params" in mockLocal.call_args.kwargs
        assert not mockGet.called

    async def test_localReceiverToken_passedInAuthHeader(self) -> None:
        """_makeLocalRequest sends localReceiverToken as the Authorization header.

        The token is forwarded verbatim (the receiver's ``get-updates-secret``
        check compares it directly), so it must appear as exactly the value
        supplied at construction.

        Args:
            None

        Returns:
            None
        """
        client = MaxBotClient(
            "test-token",
            basePollingUrl="http://127.0.0.1:8443",
            localReceiverToken="my-secret",
        )

        fakeResponse = _FakeResponse(_EMPTY_UPDATES_RESPONSE)
        mockClient = AsyncMock()
        mockClient.__aenter__.return_value = mockClient
        mockClient.get.return_value = fakeResponse

        with patch("httpx.AsyncClient", return_value=mockClient):
            await client._makeLocalRequest("/updates", params={"limit": 10})

        sentHeaders = mockClient.get.call_args.kwargs["headers"]
        assert sentHeaders.get("Authorization") == "my-secret"

    async def test_noLocalReceiverToken_noAuthHeader(self) -> None:
        """_makeLocalRequest omits Authorization when no token is configured.

        Without a ``localReceiverToken`` no ``Authorization`` header must be
        sent to the local receiver — in particular the bot access token must
        never leak onto the local poll.

        Args:
            None

        Returns:
            None
        """
        client = MaxBotClient("test-token", basePollingUrl="http://127.0.0.1:8443")

        fakeResponse = _FakeResponse(_EMPTY_UPDATES_RESPONSE)
        mockClient = AsyncMock()
        mockClient.__aenter__.return_value = mockClient
        mockClient.get.return_value = fakeResponse

        with patch("httpx.AsyncClient", return_value=mockClient):
            await client._makeLocalRequest("/updates")

        sentHeaders = mockClient.get.call_args.kwargs["headers"]
        assert "Authorization" not in sentHeaders

    def test_basePollingUrl_storedInSlots(self) -> None:
        """_basePollingUrl is stored and accessible on the client.

        When supplied it holds the (slash-stripped) URL; when omitted it is
        ``None``.

        Args:
            None

        Returns:
            None
        """
        client = MaxBotClient("test-token", basePollingUrl="http://127.0.0.1:8443")
        assert client._basePollingUrl == "http://127.0.0.1:8443"

        clientNoUrl = MaxBotClient("test-token")
        assert clientNoUrl._basePollingUrl is None

    async def test_basePollingUrl_trailingSlashStripped(self) -> None:
        """Trailing slash on basePollingUrl is stripped before URL construction.

        Verifies both the stored attribute and the assembled local URL so a
        trailing slash in config cannot produce a ``//updates`` path.

        Args:
            None

        Returns:
            None
        """
        client = MaxBotClient("test-token", basePollingUrl="http://127.0.0.1:8443/")
        assert client._basePollingUrl == "http://127.0.0.1:8443"

        fakeResponse = _FakeResponse(_EMPTY_UPDATES_RESPONSE)
        mockClient = AsyncMock()
        mockClient.__aenter__.return_value = mockClient
        mockClient.get.return_value = fakeResponse

        with patch("httpx.AsyncClient", return_value=mockClient):
            await client._makeLocalRequest("/updates")

        requestedUrl = mockClient.get.call_args.args[0]
        assert requestedUrl == "http://127.0.0.1:8443/updates"
