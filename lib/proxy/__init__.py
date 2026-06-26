"""Proxy resolution module.

Provides stateless helpers for resolving, building, and masking proxy
configuration.  Used by services that need to route outbound HTTP requests
through an HTTP or SOCKS5 proxy.

This module lives in ``lib/`` and has **no** imports from ``internal/``.
"""

import logging
from enum import StrEnum
from threading import Lock
from typing import Any, Dict, Optional, TypedDict, cast
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


class HealthCheckType(StrEnum):
    """Health check mechanism for proxy lifecycle management."""

    NONE = "none"
    """No health monitoring."""
    URL = "url"
    """HTTP GET through the proxy to a configurable URL; 2xx = pass."""
    COMMAND = "command"
    """Run a shell command; exit 0 = pass."""


class ProxyConfigDict(TypedDict, total=False):
    """Resolved proxy configuration for a single service.

    Attributes:
        enabled: Whether this proxy config is enabled. True means "use this
            config"; False means "inherit from global" in getCombined().
        type: Proxy protocol type — NONE, HTTP or SOCKS5. Defaults to NONE.
        address: Full proxy URL including scheme and port
            (e.g., "http://proxy:8080", "socks5://proxy:1080").
        user: Username for proxy authentication. None means "inherit from
            global"; empty string means "no auth, override global."
        password: Password for proxy authentication. None means "inherit
            from global"; empty string means "no auth, override global."
    """

    enabled: bool
    type: ProxyType
    address: str
    user: str
    password: str


class ProxyLifecycleConfigDict(TypedDict, total=False):
    """Lifecycle configuration for a managed proxy process.

    All fields are optional. Omitting the entire section disables lifecycle
    management. When present, the proxy process is started at application
    startup, health-checked periodically, and stopped at shutdown.

    Attributes:
        startCommand: Command and arguments to start the proxy process.
            Executed via asyncio.create_subprocess_exec on startup.
        stopCommand: Command and arguments to stop the proxy process.
            Executed on shutdown and as part of restart.
        restartCommand: Command and arguments to restart the proxy.
            If present, used instead of stop+start on health-check failure.
        healthCheckType: Type of health check — NONE, URL, or COMMAND.
            Defaults to NONE (no monitoring).
        healthCheckUrl: URL to probe when healthCheckType is URL.
        healthCheckCommand: Command to run when healthCheckType is COMMAND.
        healthCheckInterval: Minutes between health checks. Defaults to 5.
    """

    startCommand: list[str]
    stopCommand: list[str]
    restartCommand: list[str]
    healthCheckType: HealthCheckType
    healthCheckUrl: str
    healthCheckCommand: list[str]
    healthCheckInterval: int


class ProxyKwargs(TypedDict, total=False):
    """Keyword arguments for httpx.AsyncClient proxy configuration.

    Contains either a ``proxy`` URL string (HTTP proxies) or a ``transport``
    instance (SOCKS5 proxies). When empty (no proxy configured), spreading
    ``**kwargs`` into ``httpx.AsyncClient()`` is a safe no-op.
    """

    proxy: str
    """HTTP proxy URL string (e.g. ``\"http://user:pass@host:8080\"``).
    Passed directly to httpx.AsyncClient(proxy=...)."""
    transport: "AsyncProxyTransport"
    """SOCKS5 transport instance from httpx_socks.AsyncProxyTransport.
    Passed to httpx.AsyncClient(transport=...)."""


def _kebabToCamelCase(key: str) -> str:
    """Convert a kebab-case string to camelCase.

    Used by :meth:`ProxyConfig.fromDict` to convert TOML kebab-case keys
    (e.g. ``\"health-check-type\"``) to Python camelCase attribute names
    (e.g. ``\"healthCheckType\"``).

    Args:
        key: A kebab-case string.

    Returns:
        The camelCase equivalent.
    """
    parts = key.split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


class ProxyConfig:
    """Resolved proxy configuration for a service.

    Represents the final proxy settings after merging per-service config
    with the global proxy config. Provides URL construction, credential
    masking, and conversion to httpx-compatible keyword arguments.

    Attributes:
        enabled: Whether this proxy configuration is enabled. When False
            on the global config, acts as a master kill-switch (all services
            get ProxyType.NONE). When False on a per-service config, the
            service inherits the global config unchanged.
        type: Proxy protocol type (NONE, HTTP, or SOCKS5). None means
            "inherit from global config in getCombined()".
        address: Proxy server address as a URL (e.g. ``"http://proxy:8080"``).
        user: Optional proxy authentication username. None means "inherit
            from global config in getCombined()"; an empty string or
            non-None value overrides the global.
        password: Optional proxy authentication password. None means
            "inherit from global config in getCombined()"; an empty string
            or non-None value overrides the global.
        lifecycle: Optional lifecycle configuration for proxy process
            management. When present, the proxy process is started at
            application startup, health-checked periodically, and stopped
            at shutdown.  Defaults to None (no lifecycle management).
    """

    __slots__ = ("type", "address", "user", "password", "enabled", "lifecycle")

    def __init__(
        self,
        proxyType: Optional[ProxyType],
        address: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        enabled: bool = True,
        lifecycle: Optional[ProxyLifecycleConfigDict] = None,
    ) -> None:
        """Initialise a proxy configuration.

        Args:
            proxyType: Proxy protocol type. None means "use default"
                (inherit from global config in getCombined()).
            address: Proxy server address as a URL
                (e.g. ``"http://proxy:8080"``). Should be provided when
                proxyType is not NONE or None; an empty or missing address will
                raise ``ValueError`` when :meth:`getProxyURL` or
                :meth:`toKwargs` is called.
            user: Optional authentication username. None means "inherit
                from global config in getCombined()"; an empty string or
                non-None value overrides the global.
            password: Optional authentication password. None means
                "inherit from global config in getCombined()"; an empty
                string or non-None value overrides the global.
            enabled: Whether this proxy configuration is enabled.
                Defaults to True.
            lifecycle: Optional lifecycle configuration for proxy process
                management. When present, commands are run at startup/
                shutdown and health checks are performed periodically.
                Defaults to None.
        """
        self.enabled = enabled
        """If this proxy config is enabled."""
        self.type = proxyType
        """Proxy Type. None means use defaults"""
        if proxyType == ProxyType.NONE:
            # In case of NONE proxy, wipe address, user and password
            address = ""
            user = ""
            password = ""

        self.address = address
        """Proxy address if type != NONE"""
        self.user = user
        """Proxy user for BASIC auth, can be empty"""
        self.password = password
        """Proxy password for BASIC auth, can be empty"""
        self.lifecycle = lifecycle
        """Optional lifecycle configuration for proxy process management."""

    @classmethod
    def fromDict(cls, data: ProxyConfigDict, *, useProxy: Optional[bool] = None) -> "ProxyConfig":
        """Create a ProxyConfig from a raw config dictionary.

        Args:
            data: Raw config dict with optional ``type``, ``address``,
                ``user``, ``password``, ``enabled``, ``lifecycle`` keys.
                Missing keys default to None (or False for enabled).
                The ``lifecycle`` sub-dict keys are expected in kebab-case
                (e.g. ``\"health-check-type\"``) and are automatically
                converted to camelCase. ProxyConfig.__init__ converts None
                address to empty string.
            useProxy: Controls proxy behaviour for this config:
                - ``False``: Force proxy to NONE type (disabled) and mark
                  config as ``enabled=True`` (so getCombined does not fall
                  back to global).
                - ``True``: Not special-cased; ``enabled`` is read from
                  ``data``.
                - ``None`` (default): Treat as global config — ``enabled``
                  is read from ``data``, preserving the master kill-switch
                  field.

        Returns:
            A ProxyConfig with the specified settings, or type NONE if
            ``useProxy`` is False.
        """

        proxyType = data.get("type")
        enabled = data.get("enabled") is True
        if useProxy is False:
            # use-proxy is False: disable proxy in this config and mark config as
            # enabled (so getCombined doesn't fall back to global).
            proxyType = ProxyType.NONE
            enabled = True
        # if useProxy is None:
        #   treat it as global config
        rawLifecycle = data.get("lifecycle")
        lifecycle: Optional[ProxyLifecycleConfigDict] = None
        if rawLifecycle is not None and isinstance(rawLifecycle, dict):
            converted: dict[str, Any] = {_kebabToCamelCase(k): v for k, v in rawLifecycle.items()}
            if "healthCheckType" in converted and isinstance(converted["healthCheckType"], str):
                try:
                    converted["healthCheckType"] = HealthCheckType(converted["healthCheckType"])
                except ValueError:
                    logger.warning(
                        "Invalid health-check-type %r; expected none, url, or command. Defaulting to NONE.",
                        converted["healthCheckType"],
                    )
                    converted["healthCheckType"] = HealthCheckType.NONE
            lifecycle = cast(ProxyLifecycleConfigDict, converted)
        return ProxyConfig(
            proxyType=proxyType,
            address=data.get("address"),
            user=data.get("user"),
            password=data.get("password"),
            enabled=enabled,
            lifecycle=lifecycle,
        )

    def copy(self) -> "ProxyConfig":
        """Return a shallow copy of this proxy configuration.

        Returns:
            A new ProxyConfig with the same type, address, user, password,
            enabled, and lifecycle values.
        """
        return ProxyConfig(
            proxyType=self.type,
            address=self.address,
            user=self.user,
            password=self.password,
            enabled=self.enabled,
            lifecycle=cast(ProxyLifecycleConfigDict, dict(self.lifecycle)) if self.lifecycle is not None else None,
        )

    def __repr__(self) -> str:
        """Return a developer-friendly string representation.

        Returns:
            A string like ``ProxyConfig(proxyType=..., address=..., ...,
            enabled=..., lifecycle=...)`` suitable for debugging.
        """
        lifecycleSummary = "present" if self.lifecycle is not None else "None"
        return (
            f"{type(self).__name__}(proxyType={self.type!r}, "
            f"address={self.address!r}, user={self.user!r}, "
            f"password={'REDACTED' if self.password else self.password!r}, "
            f"enabled={self.enabled!r}, lifecycle={lifecycleSummary})"
        )

    def __str__(self) -> str:
        """Return a human-readable string representation.

        Delegates to :meth:`__repr__`.

        Returns:
            The same string as :meth:`__repr__`.
        """
        return self.__repr__()

    @classmethod
    def fromServiceConfig(cls, data: Dict[str, Any]) -> "ProxyConfig":
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

        Implements a two-level kill-switch:

        1. **Master kill-switch**: If the global proxy config is disabled
           (``globalProxyConfig.enabled`` is ``False``), returns a ProxyConfig
           with type NONE — no proxy for any service, regardless of per-service
           settings.

        2. **Service kill-switch**: If this service-level config is disabled
           (``self.enabled`` is ``False``), returns a copy of the global
           proxy config unchanged (the service inherits the global proxy).

        3. **Both enabled**: Merges service values with global fallback.
           Service-level fields take precedence; a non-None, non-empty
           service value overrides the global. For ``user`` and ``password``,
           ``None`` means "inherit from global", while an empty string or
           non-None value overrides the global setting.

        Returns:
            A ProxyConfig with fields resolved from service and global configs,
            respecting the kill-switch hierarchy.
        """
        globalProxyConfig = ProxyHelper.getInstance().getGlobalProxyConfig()

        # If global config is disabled, then no proxy at all
        if not globalProxyConfig.enabled:
            return ProxyConfig(proxyType=ProxyType.NONE)

        # If local config is disabled,
        if not self.enabled:
            return globalProxyConfig.copy()

        # both configs are enabled, use local with fallback to global
        return ProxyConfig(
            proxyType=self.type or globalProxyConfig.type or ProxyType.NONE,
            address=self.address or globalProxyConfig.address,
            user=self.user if self.user is not None else globalProxyConfig.user,
            password=self.password if self.password is not None else globalProxyConfig.password,
            lifecycle=self.lifecycle if self.lifecycle is not None else globalProxyConfig.lifecycle,
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
            address=config.address or "",
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
            address=config.address or "",
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
        All ProxyConfig.getCombined() calls will use this stored value as
        the global proxy config.

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
            The stored global ProxyConfig instance.

        Raises:
            TypeError: If setGlobalProxyConfig() has not been called yet.
        """
        if self.globalProxyConfig is None:
            raise TypeError("need to call setGlobalProxyConfig() first")

        return self.globalProxyConfig
