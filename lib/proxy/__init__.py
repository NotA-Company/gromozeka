"""Proxy resolution module.

Provides stateless helpers for resolving, building, and masking proxy
configuration.  Used by services that need to route outbound HTTP requests
through an HTTP or SOCKS5 proxy.

This module lives in ``lib/`` and has **no** imports from ``internal/``.
"""

import logging
from enum import StrEnum
from threading import Lock
from typing import Any, Dict, Optional, TypedDict
from urllib.parse import quote, urlparse, urlunparse

try:
    from httpx_socks import AsyncProxyTransport

    _HTTPX_SOCKS_AVAILABLE = True
except ImportError:
    _HTTPX_SOCKS_AVAILABLE = False


logger = logging.getLogger(__name__)


class ProxyType(StrEnum):
    """Supported proxy protocol types."""

    NONE = "none"
    """Proxy disabled."""
    HTTP = "http"
    """HTTP/HTTPS proxy."""
    SOCKS5 = "socks5"
    """SOCKS5 proxy (requires httpx-socks[asyncio] package)."""


class ProxyConfigDict(TypedDict, total=False):
    """Resolved proxy configuration for a single service.

    Attributes:
        type: Proxy protocol type — NONE, HTTP or SOCKS5. Defaults to NONE.
        address: Full proxy URL including scheme and port
            (e.g., "http://proxy:8080", "socks5://proxy:1080").
        user: Username for proxy authentication. Empty string if no auth.
        password: Password for proxy authentication. Empty string if no auth.
    """

    enabled: bool
    type: ProxyType
    address: str
    user: str
    password: str


class ProxyKwargs(TypedDict, total=False):
    """Keyword arguments for httpx.AsyncClient proxy configuration.

    Contains either a ``proxy`` URL string (HTTP proxies) or a ``transport``
    instance (SOCKS5 proxies). When empty (no proxy configured), spreading
    ``**kwargs`` into ``httpx.AsyncClient()`` is a safe no-op.
    """

    proxy: str
    """HTTP proxy URL string (e.g. ``\"http://user:pass@host:8080\"``).
    Passed directly to httpx.AsyncClient(proxy=...)."""
    transport: AsyncProxyTransport
    """SOCKS5 transport instance from httpx_socks.AsyncProxyTransport.
    Passed to httpx.AsyncClient(transport=...)."""


class ProxyConfig:
    """Resolved proxy configuration for a service.

    Represents the final proxy settings after merging per-service config
    with the global proxy config. Provides URL construction, credential
    masking, and conversion to httpx-compatible keyword arguments.

    Attributes:
        type: Proxy protocol type (NONE, HTTP, or SOCKS5).
        address: Proxy server address as a URL (e.g. ``"http://proxy:8080"``).
        user: Optional proxy authentication username.
        password: Optional proxy authentication password.
    """

    __slots__ = ("type", "address", "user", "password")

    def __init__(
        self,
        proxyType: Optional[ProxyType],
        address: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.type = proxyType
        """Proxy Type. None means use defaults"""
        if proxyType != ProxyType.NONE and proxyType is not None:
            if not address:
                raise ValueError("address should be valid proxy address in case of proxyType != NONE")
        elif proxyType == ProxyType.NONE:
            # In case of NONE proxy, wipe address, user and password
            address = ""
            user = ""
            password = ""

        self.address: str = address or ""
        """Proxy address if type != NONE"""
        self.user = user
        """Proxy user for BASIC auth, can be empty"""
        self.password = password
        """Proxy password for BASIC auth, can be empty"""

    @classmethod
    def fromDict(cls, data: ProxyConfigDict, *, useProxy: Optional[bool] = None) -> "ProxyConfig":
        """Create a ProxyConfig from a raw config dictionary.

        Args:
            data: Raw config dict with optional ``type``, ``address``, ``user``,
                ``password`` keys. Missing keys default to empty strings.
            useProxy: Whether proxy is enabled for this service. If False,
                returns a ProxyConfig with type NONE regardless of other fields.

        Returns:
            A ProxyConfig with the specified settings, or type NONE if
            ``useProxy`` is False or no address is provided.
        """
        if useProxy is None:
            useProxy = data.get("enabled") is True
        return ProxyConfig(
            proxyType=data.get("type") if useProxy else ProxyType.NONE,
            address=data.get("address"),
            user=data.get("user"),
            password=data.get("password"),
        )

    @classmethod
    def fromServiceDict(cls, data: Dict[str, Any]) -> "ProxyConfig":
        """Create a ProxyConfig from a per-service TOML config dict.

        Reads the ``use-proxy`` (bool) and ``proxy`` (dict) keys from the
        config. If ``use-proxy`` is True and a ``proxy`` section exists,
        creates a ProxyConfig from that section. Otherwise returns type NONE.

        Args:
            data: Per-service config dict with optional ``use-proxy`` and
                ``proxy`` keys (as merged from TOML).

        Returns:
            A ProxyConfig from the service's proxy section, or type NONE
            if proxy is not enabled for this service.
        """
        return cls.fromDict(
            data=data.get("proxy", {}),
            useProxy=data.get("use-proxy", False) is True,
        )

    def _buildProxyUrl(self, address: str, user: str, password: str) -> str:
        """Build a full proxy URL with embedded credentials.

        Constructs ``scheme://[user:password@]host:port`` from the resolved
        :class:`ProxyConfig`.  If *user* is empty the address is returned
        unchanged.

        Args:
            address: Proxy server URL (e.g. ``"http://proxy:8080"``).
            user: Optional proxy authentication username.
            password: Optional proxy authentication password.

        Returns:
            The proxy URL string, or ``""`` if the address is empty.
            May contain plaintext credentials — use
            ``getProxyURL(maskPassword=True)`` for safe logging.
        """
        parsed = urlparse(address)
        if not parsed.hostname:
            raise ValueError(f"Cannot build proxy URL: address is missing or unparseable: " f"{address!r}")

        if not user:
            return address

        netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{parsed.hostname}"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc))

    def getCombined(self) -> "ProxyConfig":
        """Merge this service-level proxy config with the global proxy config.

        Each field (type, address, user, password) uses the service value
        if set (non-None, non-empty), falling back to the global config
        from ProxyHelper. If the service config has type NONE, the result
        is also NONE (proxy disabled for this service).

        Returns:
            A ProxyConfig with fields resolved from service and global configs.
        """
        globalProxyConfig = ProxyHelper.getInstance().getGlobalProxyConfig()
        return ProxyConfig(
            proxyType=self.type or globalProxyConfig.type or ProxyType.NONE,
            address=self.address or globalProxyConfig.address,
            user=self.user if self.user is not None else globalProxyConfig.user,
            password=self.password if self.password is not None else globalProxyConfig.password,
        )

    def getProxyURL(self, *, maskPassword: bool = False) -> Optional[str]:
        """Build the proxy URL string.

        Args:
            maskPassword: If True, replace the password with ``"REDACTED"``
                for safe logging. Default is False.

        Returns:
            The proxy URL string (e.g. ``"http://user:pass@host:8080"``),
            or None if proxy type is NONE or address is empty.
        """
        config = self.getCombined()

        if config.type == ProxyType.NONE or config.type is None:
            return None

        return self._buildProxyUrl(
            address=config.address,
            user=config.user or "",
            password=(config.password or "") if not maskPassword else "REDACTED",
        )

    def toKwargs(self) -> ProxyKwargs:
        """Convert this proxy config to httpx-compatible keyword arguments.

        Returns:
            A ProxyKwargs TypedDict with either ``proxy`` key (HTTP) or
            ``transport`` key (SOCKS5). Returns an empty dict when proxy
            type is NONE (spreading into httpx.AsyncClient is a no-op).

        Raises:
            ImportError: If proxy type is SOCKS5 and the httpx-socks package
                is not installed.
        """
        config = self.getCombined()

        if config.type == ProxyType.NONE or config.type is None:
            return ProxyKwargs()

        proxyUrl = self._buildProxyUrl(
            address=config.address,
            user=config.user or "",
            password=config.password or "",
        )

        if config.type == ProxyType.HTTP:
            return ProxyKwargs(proxy=proxyUrl)

        if config.type == ProxyType.SOCKS5:
            if not _HTTPX_SOCKS_AVAILABLE:
                raise ImportError(
                    "SOCKS5 proxy requires httpx-socks[asyncio] package. "
                    "Install with: pip install httpx-socks[asyncio]"
                )
            return ProxyKwargs(transport=AsyncProxyTransport.from_url(proxyUrl))

        raise ValueError(f"Unsupported proxy type: {config.type!r}. Must be 'none', 'http' or 'socks5'.")


class ProxyHelper:
    """Singleton that stores the global proxy configuration.

    Set once at application startup via setGlobalProxyConfig() and
    accessed by all proxy-using services via getGlobalProxyConfig().
    Follows the project's singleton pattern with getInstance() classmethod
    and hasattr(self, 'initialized') guard.
    """

    _instance: "ProxyHelper | None" = None
    """The singleton instance, or None if not yet created."""

    _lock = Lock()
    """Thread lock protecting singleton initialization."""

    def __new__(cls) -> "ProxyHelper":
        """Create or return the singleton instance.

        Args:
            cls: The ProxyHelper class.

        Returns:
            The singleton ProxyHelper instance.
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    @classmethod
    def getInstance(cls) -> "ProxyHelper":
        """Get or create the singleton ProxyHelper instance.

        The global proxy configuration should be set via
        :meth:`setGlobalProxyConfig` before the first call if proxy support
        is needed, otherwise ``getGlobalProxyConfig()`` will raise a
        :class:`TypeError`.

        Args:
            cls: The ProxyHelper class.

        Returns:
            The singleton ProxyHelper instance.
        """
        if cls._instance is None:
            return cls()
        return cls._instance

    def __init__(self) -> None:
        """Initialise the proxy helper.

        Only the first call executes; subsequent calls are guarded by the
        hasattr(self, 'initialized') sentinel.

        Args:
            self: The ProxyHelper instance.
        """
        if hasattr(self, "initialized"):
            return
        self.initialized = True
        self.globalProxyConfig: Optional[ProxyConfig] = None

    def setGlobalProxyConfig(self, proxyConfig: Optional[ProxyConfigDict]) -> None:
        """Store the global proxy configuration for the application lifetime.

        Call once at startup with the result of ConfigManager.getProxyConfig().
        All resolveProxyConfig() calls without an explicit globalProxy argument
        will use this stored value.

        Args:
            proxyConfig: The global [proxy] config dict from ConfigManager,
                or None to clear.
        """
        if proxyConfig is None:
            proxyConfig = {}
        self.globalProxyConfig = ProxyConfig.fromDict(proxyConfig)

    def getGlobalProxyConfig(self) -> ProxyConfig:
        """Return the stored global proxy configuration.

        Returns:
            The global [proxy] config dict, or None if not yet set.
        """
        if self.globalProxyConfig is None:
            raise TypeError("need to call setGlobalProxyConfig() first")

        return self.globalProxyConfig
