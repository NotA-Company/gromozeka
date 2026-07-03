"""Unit tests for the Max Messenger Bot API migration changes.

Covers three migration concerns:

1. Endpoint migration — ``API_BASE_URL`` now points at ``platform-api2.max.ru``
   and ``DEFAULT_RATE_LIMIT`` dropped from 100 to 30 rps (enforced by the new
   endpoint). ``MAX_RETRIES`` is asserted unchanged as a sanity check.
2. Custom CA trust — ``lib.max_bot.utils.buildMaxSslContext`` builds an
   ``ssl.SSLContext`` that loads the Минцифры root/sub CA PEMs from ``certs/max``
   on top of the system defaults.
3. CA bundle path pass-through — ``MaxBotClient`` accepts an optional
   ``caBundlePath`` and builds the SSL context internally via
   ``buildMaxSslContext()``, then forwards it to ``httpx.AsyncClient`` as
   ``verify=`` only when provided (and threads it into the SOCKS5 transport
   when a SOCKS5 proxy is configured).

Tests use the real CA bundle checked into ``certs/max/`` (these are public
certificates, not secrets) and ``unittest.mock`` to inspect the httpx kwargs
without performing any network I/O.
"""

import ssl
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lib.max_bot.client import MaxBotClient
from lib.max_bot.constants import API_BASE_URL, DEFAULT_RATE_LIMIT, MAX_RETRIES
from lib.max_bot.utils import buildMaxSslContext
from lib.proxy import ProxyConfig, ProxyHelper, ProxyType

# Path to the public CA bundle committed for the Max API migration.
_MAX_CERTS_DIR = "certs/max"


def testApiBaseUrlIsNewEndpoint() -> None:
    """Verify API_BASE_URL points to platform-api2.max.ru.

    Args:
        None

    Returns:
        None
    """
    assert API_BASE_URL == "https://platform-api2.max.ru"


def testDefaultRateLimitIs30() -> None:
    """Verify DEFAULT_RATE_LIMIT reflects the new API's 30 rps limit.

    The legacy ``platform-api.max.ru`` endpoint allowed 100 rps; the migrated
    ``platform-api2.max.ru`` endpoint enforces 30 rps.

    Args:
        None

    Returns:
        None
    """
    assert DEFAULT_RATE_LIMIT == 30


def testMaxRetriesIs5() -> None:
    """Verify MAX_RETRIES is still 5 (unchanged by the migration).

    Args:
        None

    Returns:
        None
    """
    assert MAX_RETRIES == 5


def testBuildMaxSslContextLoadsFromCertsDir() -> None:
    """Verify buildMaxSslContext loads PEM files from the certs/max directory.

    Uses the real public CA bundle committed under ``certs/max/`` to prove the
    PEMs are valid and loadable into an ``ssl.SSLContext``.

    Args:
        None

    Returns:
        None
    """
    ctx = buildMaxSslContext(_MAX_CERTS_DIR)
    assert ctx is not None
    assert isinstance(ctx, ssl.SSLContext)


def testBuildMaxSslContextNoneReturnsNone() -> None:
    """Verify None return when caBundlePath is None.

    Args:
        None

    Returns:
        None
    """
    assert buildMaxSslContext(None) is None


def testBuildMaxSslContextEmptyStringReturnsNone() -> None:
    """Verify None return when caBundlePath is an empty string.

    Args:
        None

    Returns:
        None
    """
    assert buildMaxSslContext("") is None


def testBuildMaxSslContextMissingDirectory() -> None:
    """Verify FileNotFoundError when the directory does not exist.

    Args:
        None

    Returns:
        None
    """
    with pytest.raises(FileNotFoundError, match="Max CA bundle directory not found"):
        buildMaxSslContext("/nonexistent/path/to/nowhere")


def testBuildMaxSslContextEmptyDirReturnsNone(tmp_path: Path) -> None:
    """Verify None return when the directory exists but has no PEM/CRT files.

    Args:
        tmp_path: Pytest fixture providing a unique temporary directory.

    Returns:
        None
    """
    result = buildMaxSslContext(str(tmp_path))
    assert result is None


async def testCaBundlePathBuildsAndPassesSslContextToHttpClient() -> None:
    """Verify caBundlePath yields an sslContext forwarded to httpx as verify=.

    When a caller supplies a ``caBundlePath`` the client builds an
    ``ssl.SSLContext`` internally via ``buildMaxSslContext()`` and forwards
    it to ``httpx.AsyncClient`` via ``verify=`` so that the Минцифры CA chain
    is trusted.

    Args:
        None

    Returns:
        None
    """
    client = MaxBotClient("test-token-for-testing", caBundlePath=_MAX_CERTS_DIR)
    ctx = client._sslContext
    assert ctx is not None

    with patch("httpx.AsyncClient") as mockAsyncClient:
        mockClient: Any = MagicMock()
        mockClient.is_closed = False
        mockClient.headers = {}
        mockAsyncClient.return_value = mockClient
        client._getHttpClient()
        callKwargs = mockAsyncClient.call_args.kwargs
        assert "verify" in callKwargs
        assert callKwargs["verify"] is ctx


async def testNoSslContextWhenCaBundlePathNone() -> None:
    """Verify verify= is NOT passed when caBundlePath is None.

    When ``caBundlePath`` is explicitly ``None`` the client must defer to
    httpx's default certificate handling — passing ``verify=None`` would
    *disable* verification, so the key must be absent entirely.

    Args:
        None

    Returns:
        None
    """
    client = MaxBotClient("test-token-for-testing", caBundlePath=None)

    with patch("httpx.AsyncClient") as mockAsyncClient:
        mockClient: Any = MagicMock()
        mockClient.is_closed = False
        mockClient.headers = {}
        mockAsyncClient.return_value = mockClient
        client._getHttpClient()
        callKwargs = mockAsyncClient.call_args.kwargs
        assert "verify" not in callKwargs


async def testNoSslContextWhenCaBundlePathOmitted() -> None:
    """Verify verify= is NOT passed when caBundlePath is omitted entirely.

    Args:
        None

    Returns:
        None
    """
    client = MaxBotClient("test-token-for-testing")

    with patch("httpx.AsyncClient") as mockAsyncClient:
        mockClient: Any = MagicMock()
        mockClient.is_closed = False
        mockClient.headers = {}
        mockAsyncClient.return_value = mockClient
        client._getHttpClient()
        callKwargs = mockAsyncClient.call_args.kwargs
        assert "verify" not in callKwargs


async def testSocks5TransportGetsSslContext() -> None:
    """Verify sslContext is threaded into the SOCKS5 transport, not verify=.

    Regression for the bug where httpx silently drops the top-level ``verify=``
    argument when a custom ``transport`` is supplied. For SOCKS5 proxies the
    SSL context must be passed to ``AsyncProxyTransport.from_url`` (via
    ``ProxyConfig.toKwargs(verify=...)``) so the Минцифры CA certs are actually
    trusted end-to-end.

    Args:
        None

    Returns:
        None
    """
    ProxyHelper.getInstance().setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
    proxyConfig = ProxyConfig(
        proxyType=ProxyType.SOCKS5,
        address="socks5://proxy.example.invalid:1080",
        user="user",
        password="pass",
    )
    client = MaxBotClient("test-token-for-testing", proxyConfig=proxyConfig, caBundlePath=_MAX_CERTS_DIR)
    ctx = client._sslContext
    assert ctx is not None

    capturedTransports: list[Any] = []

    class _FakeTransport:
        """Stub replacing httpx_socks.AsyncProxyTransport for capture."""

        @classmethod
        def from_url(cls, url: str, **kwargs: Any) -> "_FakeTransport":
            capturedTransports.append(kwargs)
            return cls()

    with patch("lib.proxy.AsyncProxyTransport", _FakeTransport), patch("httpx.AsyncClient") as mockAsyncClient:
        mockClient: Any = MagicMock()
        mockClient.is_closed = False
        mockClient.headers = {}
        mockAsyncClient.return_value = mockClient
        client._getHttpClient()

    callKwargs = mockAsyncClient.call_args.kwargs
    # The SSL context must NOT live on the client-level verify= (it would be
    # ignored by httpx in the presence of a custom transport).
    assert "transport" in callKwargs
    assert "verify" not in callKwargs
    # The transport itself must have been built with verify=ctx.
    assert len(capturedTransports) == 1
    transportKwargs = capturedTransports[0]
    assert transportKwargs.get("verify") is ctx


async def testSocks5TransportWithoutSslContextUnchanged() -> None:
    """Verify SOCKS5 path is untouched when caBundlePath is None.

    When no custom CA context is supplied the existing behaviour (transport
    built by ``ProxyConfig.toKwargs()`` with system-default TLS) must be
    preserved — a single transport build, no verify= on the client.

    Args:
        None

    Returns:
        None
    """
    ProxyHelper.getInstance().setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
    proxyConfig = ProxyConfig(
        proxyType=ProxyType.SOCKS5,
        address="socks5://proxy.example.invalid:1080",
    )
    client = MaxBotClient("test-token-for-testing", proxyConfig=proxyConfig, caBundlePath=None)

    capturedTransports: list[Any] = []

    class _FakeTransport:
        @classmethod
        def from_url(cls, url: str, **kwargs: Any) -> "_FakeTransport":
            capturedTransports.append(kwargs)
            return cls()

    with patch("lib.proxy.AsyncProxyTransport", _FakeTransport), patch("httpx.AsyncClient") as mockAsyncClient:
        mockClient: Any = MagicMock()
        mockClient.is_closed = False
        mockClient.headers = {}
        mockAsyncClient.return_value = mockClient
        client._getHttpClient()

    callKwargs = mockAsyncClient.call_args.kwargs
    # toKwargs() builds the transport exactly once; no recreation.
    assert len(capturedTransports) == 1
    assert "transport" in callKwargs
    assert "verify" not in callKwargs
    # No verify threaded into the transport either.
    assert "verify" not in capturedTransports[0]


async def testHttpProxyKeepsVerifyOnClient() -> None:
    """Verify HTTP (non-SOCKS5) proxy keeps verify= on the client level.

    For HTTP proxies ``toKwargs()`` sets ``proxy=`` (not ``transport=``), so
    httpx still honours the top-level ``verify=``. The SOCKS5 threading must
    not interfere.

    Args:
        None

    Returns:
        None
    """
    ProxyHelper.getInstance().setGlobalProxyConfig({"enabled": True, "type": ProxyType.NONE, "address": ""})
    proxyConfig = ProxyConfig(
        proxyType=ProxyType.HTTP,
        address="http://proxy.example.invalid:8080",
    )
    client = MaxBotClient("test-token-for-testing", proxyConfig=proxyConfig, caBundlePath=_MAX_CERTS_DIR)
    ctx = client._sslContext
    assert ctx is not None

    with patch("httpx.AsyncClient") as mockAsyncClient:
        mockClient: Any = MagicMock()
        mockClient.is_closed = False
        mockClient.headers = {}
        mockAsyncClient.return_value = mockClient
        client._getHttpClient()

    callKwargs = mockAsyncClient.call_args.kwargs
    assert "transport" not in callKwargs
    assert callKwargs.get("proxy") == "http://proxy.example.invalid:8080"
    assert callKwargs.get("verify") is ctx
