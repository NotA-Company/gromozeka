# Proxy Support — Comprehensive Implementation Plan

> **Status:** READY FOR IMPLEMENTATION  
> **Last updated:** 2026-05-23  
> **Supersedes:** Discussion draft (same path)

---

## Table of Contents

1. [Goal & Non-Goals](#1-goal--non-goals)
2. [Config TOML Structure — Full Spec](#2-config-toml-structure--full-spec)
3. [Shared Module: `lib/proxy.py` — Full API Spec](#3-shared-module-libproxypy--full-api-spec)
4. [ConfigManager Changes](#4-configmanager-changes)
5. [Per-Service Wiring — Exact Code Changes](#5-per-service-wiring--exact-code-changes)
6. [SOCKS5 Dependency](#6-socks5-dependency)
7. [Implementation Phases](#7-implementation-phases)
8. [Testing Strategy](#8-testing-strategy)
9. [Risks & Mitigations](#9-risks--mitigations)
10. [Documentation Impact](#10-documentation-impact)

---

## 1. Goal & Non-Goals

### Goal

Route outbound HTTP traffic through configurable HTTP/SOCKS5 proxies. Each service
opts in with a `use-proxy` boolean flag and can optionally override the global proxy.
Proxy is **disabled by default** — zero behavioral change for existing deployments.

### Non-Goals

| Excluded | Reason |
|---|---|
| **YC SDK provider (gRPC)** | gRPC uses a fundamentally different proxy model (`grpc.aio.channel` options). Out of scope for v1; can be added later with a gRPC-specific helper. |
| **Sandbox / Docker backend** | Container networking uses Docker bridge/host networking. Proxy for containers requires `docker run --env HTTP_PROXY=...` or custom network config — too complex for v1. |
| **Hot-reload of proxy config** | Config is loaded once at startup. Changing proxy config requires a restart. Acceptable for v1. |
| **Proxy authentication beyond Basic Auth** | NTLM, Kerberos, client certificates are out of scope. HTTP Basic Auth and SOCKS5 username/password are supported. |
| **Per-request proxy selection** | All requests for a given service go through the same proxy. No request-level routing. |
| **`NO_PROXY` / bypass lists** | Not needed for v1; all traffic for an opted-in service goes through the proxy. |
| **Database changes** | No schema or migration changes needed. |
| **Chat settings** | Proxy is an operator/infrastructure concern, not a per-chat setting. |

---

## 2. Config TOML Structure — Full Spec

### 2.1 New file: `configs/00-defaults/proxy.toml`

```toml
# Global proxy configuration.
# Used by any service that sets use-proxy = true and does not provide
# its own [<service>.proxy-override] sub-section.
[proxy]
# Master kill-switch. When false, NO service uses proxy regardless of
# per-service use-proxy flags.
enabled = false

# Proxy type: "http" or "socks5"
type = "http"

# Full proxy address including scheme and port.
# Examples:
#   HTTP:   "http://proxy.example.com:8080"
#   SOCKS5: "socks5://proxy.example.com:1080"
# Use ${ENV_VAR} substitution for secrets.
address = ""

# Optional credentials for proxy authentication (Basic Auth for HTTP,
# username/password for SOCKS5). Leave empty if no auth is required.
# Use ${ENV_VAR} substitution — never commit credentials.
user = ""
password = ""
```

### 2.2 Additions to `configs/00-defaults/bot-defaults.toml`

Append at the very end of file (after line 308):

```toml
# --- Proxy ---
# Whether the bot platform (Telegram / Max) should route traffic through
# the global proxy. Requires [proxy].enabled = true globally.
[bot]
use-proxy = false
# Per-service proxy override (uncomment to use a different proxy for the bot):
# [bot.proxy-override]
# type = "socks5"
# address = "${BOT_PROXY_ADDRESS}"
# user = "${BOT_PROXY_USER}"
# password = "${BOT_PROXY_PASSWORD}"
```

**Note:** Because `bot-defaults.toml` already contains many `[bot.*]` sections,
and TOML merging is recursive, adding `use-proxy` under `[bot]` will merge
correctly with the existing `[bot]` table. The implementer should place it inside
the existing `[bot.defaults]` section or at the top-level `[bot]` — the safest
spot is a new `[bot]` header at the end of the file since `_mergeConfigs` will
merge it into the existing `[bot]` dict.

### 2.3 Additions to `configs/00-defaults/providers.toml`

Append after line 15:

```toml
# --- Proxy per provider ---
# Each provider can independently opt in to proxy.
# The use-proxy flag goes inside the provider's existing config section.
# The proxy-override sub-table uses the same keys as [proxy].

# Example (uncomment to enable):
# [models.providers.yc-openai]
# use-proxy = false
#
# [models.providers.yc-openai.proxy-override]
# type = "http"
# address = "${YC_PROXY_ADDRESS}"
#
# [models.providers.openrouter]
# use-proxy = false
```

**Implementation note:** Since each provider's config dict is passed directly to
the provider constructor at `lib/ai/manager.py:125`, the `use-proxy` and
`proxy-override` keys will already be present in `provider_config` without any
additional plumbing.

### 2.4 Additions to `configs/00-defaults/00-config.toml`

Add `use-proxy = false` to each service section. Exact insertion points:

| Section | Insert after line | Addition |
|---|---|---|
| `[openweathermap]` | line 84 (after `enabled = false`) | `use-proxy = false` |
| `[geocode-maps]` | line 103 (after `enabled = false`) | `use-proxy = false` |
| `[yandex-search]` | line 113 (after `enabled = false`) | `use-proxy = false` |

Each section can also have a `[<section>.proxy-override]` sub-table with the
same `type`/`address`/`user`/`password` keys as `[proxy]`.

### 2.5 `${ENV_VAR}` Substitution Rules

The existing `substituteEnvVars()` in `internal/config/manager.py:54-76` handles
`${VAR_NAME}` recursively in strings, dicts, and lists. No changes needed.
Operators should put proxy credentials in `.env*` files:

```bash
# In .env.local (never committed)
PROXY_ADDRESS="http://proxy.corp.example.com:8080"
PROXY_USER="bot-user"
PROXY_PASSWORD="s3cret"
```

And reference them in a local TOML override:

```toml
# configs/local/proxy.toml
[proxy]
enabled = true
address = "${PROXY_ADDRESS}"
user = "${PROXY_USER}"
password = "${PROXY_PASSWORD}"
```

---

## 3. Shared Module: `lib/proxy.py` — Full API Spec

### 3.1 Module Overview

New file at `lib/proxy.py`. Lives in `lib/` — **no imports from `internal/`**.
Provides proxy resolution logic and httpx client kwargs construction.

### 3.2 Imports

```python
import logging
from typing import Any, Dict, Literal, Optional

from typing_extensions import TypedDict

logger = logging.getLogger(__name__)
```

The `httpx_socks` import is conditional (see section 6).

### 3.3 Types

```python
ProxyType = Literal["http", "socks5"]
"""Supported proxy protocol types."""


class ProxyConfig(TypedDict, total=False):
    """Resolved proxy configuration for a single service.

    Attributes:
        type: Proxy protocol type — "http" or "socks5".
        address: Full proxy URL including scheme and port
            (e.g., "http://proxy:8080", "socks5://proxy:1080").
        user: Username for proxy authentication. Empty string if no auth.
        password: Password for proxy authentication. Empty string if no auth.
    """

    type: ProxyType
    address: str
    user: str
    password: str
```

### 3.4 `resolveProxyConfig()`

```python
def resolveProxyConfig(
    globalProxy: Dict[str, Any],
    serviceConfig: Dict[str, Any],
) -> Optional[ProxyConfig]:
    """Resolve the effective proxy configuration for a service.

    Implements a 4-step resolution algorithm:

    1. If globalProxy is empty or globalProxy["enabled"] is falsy -> return None.
       (Master kill-switch: no proxy for anyone.)
    2. If serviceConfig.get("use-proxy") is falsy (False, absent, 0, "") -> return None.
       (Service has not opted in.)
    3. If serviceConfig contains a "proxy-override" dict with a non-empty "address" key,
       build ProxyConfig from the override, falling back to global values for any
       missing fields.
    4. Otherwise, build ProxyConfig from the global proxy settings.

    Edge cases:
    - Empty string for "address" in proxy-override is treated as "no override" (fall through to step 4).
    - Missing "type" defaults to "http".
    - Missing "user" or "password" defaults to "".
    - If global proxy has enabled=true but address is empty -> return None with a warning.

    Args:
        globalProxy: The [proxy] section from config (Dict[str, Any]).
        serviceConfig: The service's config section (e.g., bot config, provider config)
            which may contain "use-proxy" (bool) and "proxy-override" (Dict).

    Returns:
        A ProxyConfig if proxy should be used, None otherwise.
    """
```

**Pseudocode:**

```
def resolveProxyConfig(globalProxy, serviceConfig):
    # Step 1: Master kill-switch
    if not globalProxy or not globalProxy.get("enabled", False):
        return None

    # Step 2: Service opt-in
    if not serviceConfig.get("use-proxy", False):
        return None

    # Step 3: Check for per-service override
    override = serviceConfig.get("proxy-override", {})
    if isinstance(override, dict) and override.get("address", "").strip():
        result = ProxyConfig(
            type=override.get("type", globalProxy.get("type", "http")),
            address=override["address"].strip(),
            user=override.get("user", globalProxy.get("user", "")),
            password=override.get("password", globalProxy.get("password", "")),
        )
        return result

    # Step 4: Use global proxy
    globalAddress = globalProxy.get("address", "").strip()
    if not globalAddress:
        logger.warning("Proxy enabled but address is empty — skipping proxy")
        return None

    return ProxyConfig(
        type=globalProxy.get("type", "http"),
        address=globalAddress,
        user=globalProxy.get("user", ""),
        password=globalProxy.get("password", ""),
    )
```

### 3.5 `buildProxyUrl()`

```python
def buildProxyUrl(proxyConfig: ProxyConfig) -> str:
    """Construct a proxy URL string from a ProxyConfig.

    Builds a URL in the format: scheme://[user:password@]host:port

    If credentials are present, they are embedded in the URL. This URL is
    suitable for passing to httpx.AsyncClient(proxy=...) for HTTP proxies
    or to httpx_socks.AsyncProxyTransport.from_url() for SOCKS5.

    SECURITY: The returned URL may contain plaintext credentials.
    Never log this URL. Use maskedProxyUrl() for logging.

    Args:
        proxyConfig: Resolved proxy configuration.

    Returns:
        Full proxy URL string with embedded credentials (if any).
    """
```

**Pseudocode:**

```
def buildProxyUrl(proxyConfig):
    address = proxyConfig["address"]
    user = proxyConfig.get("user", "")
    password = proxyConfig.get("password", "")

    if not user:
        return address

    # Parse address to inject credentials
    # address is like "http://host:port" or "socks5://host:port"
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(address)
    netloc = f"{user}:{password}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
```

### 3.6 `maskedProxyUrl()`

```python
def maskedProxyUrl(proxyConfig: ProxyConfig) -> str:
    """Return a proxy URL safe for logging (password masked).

    Args:
        proxyConfig: Resolved proxy configuration.

    Returns:
        URL string with password replaced by "***" if credentials are present.
        Example: "socks5://user:***@proxy.example.com:1080"
    """
```

### 3.7 `buildHttpxClientKwargs()`

```python
def buildHttpxClientKwargs(proxyConfig: Optional[ProxyConfig]) -> Dict[str, Any]:
    """Build keyword arguments to spread into httpx.AsyncClient(...).

    Returns different kwargs depending on proxy type:
    - No proxy (proxyConfig is None):  {}
    - HTTP proxy:   {"proxy": "http://user:pass@host:port"}
    - SOCKS5 proxy: {"transport": AsyncProxyTransport.from_url("socks5://...")}

    For SOCKS5, this function imports httpx_socks lazily and constructs an
    AsyncProxyTransport. If httpx_socks is not installed and type is "socks5",
    raises ImportError with a helpful message.

    IMPORTANT: The returned dict may contain objects that hold credentials.
    Do not log the dict or its values.

    Args:
        proxyConfig: Resolved proxy configuration, or None if no proxy.

    Returns:
        Dict of kwargs to spread into httpx.AsyncClient constructor.
        Empty dict if proxyConfig is None.

    Raises:
        ImportError: If SOCKS5 proxy is configured but httpx-socks is not installed.
    """
```

**Pseudocode:**

```
def buildHttpxClientKwargs(proxyConfig):
    if proxyConfig is None:
        return {}

    url = buildProxyUrl(proxyConfig)
    proxyType = proxyConfig.get("type", "http")

    if proxyType == "socks5":
        # Conditional import — only needed for SOCKS5
        try:
            from httpx_socks import AsyncProxyTransport
        except ImportError:
            raise ImportError(
                "httpx-socks is required for SOCKS5 proxy support. "
                "Install it: pip install httpx-socks[asyncio]"
            )
        transport = AsyncProxyTransport.from_url(url)
        return {"transport": transport}
    else:
        # HTTP proxy — httpx handles natively via proxy= parameter
        return {"proxy": url}
```

### 3.8 Complete Module Outline

```
lib/proxy.py
  Module docstring
  Imports: logging, typing, urllib.parse, typing_extensions
  ProxyType = Literal["http", "socks5"]
  class ProxyConfig(TypedDict, total=False)
  def resolveProxyConfig(globalProxy, serviceConfig) -> Optional[ProxyConfig]
  def buildProxyUrl(proxyConfig) -> str
  def maskedProxyUrl(proxyConfig) -> str
  def buildHttpxClientKwargs(proxyConfig) -> Dict[str, Any]
```

All functions are module-level, stateless, and pure (except `buildHttpxClientKwargs`
which does a conditional import). No classes beyond the TypedDict.

---

## 4. ConfigManager Changes

### 4.1 New Method: `getProxyConfig()`

**File:** `internal/config/manager.py`  
**Insert after:** `getStatsConfig()` method (line 496, end of file)  
**Insert before:** End of class / end of file

```python
def getProxyConfig(self) -> Dict[str, Any]:
    """Get global proxy configuration.

    Returns the [proxy] section from the merged config. This dict is passed
    to resolveProxyConfig() from lib.proxy along with a service's own config
    to determine whether and how to proxy that service's traffic.

    Returns:
        Dictionary containing proxy configuration with keys:
            - enabled (bool): Master kill-switch for proxy
            - type (str): "http" or "socks5"
            - address (str): Proxy URL
            - user (str): Optional proxy username
            - password (str): Optional proxy password
        Returns an empty dict if [proxy] section is not configured.

    Example:
        >>> config_manager = ConfigManager()
        >>> proxy_config = config_manager.getProxyConfig()
        >>> print(proxy_config.get("enabled"))
        False
    """
    return self.get("proxy", {})
```

This follows the exact pattern of every other getter in the class (`getBotConfig`,
`getDatabaseConfig`, `getOpenWeatherMapConfig`, etc.) — each is a one-liner
wrapping `self.get()`.

---

## 5. Per-Service Wiring — Exact Code Changes

### 5.1 Telegram Bot

**Files:**
- `internal/bot/telegram/application.py` — `TelegramBotApplication.run()` (lines 340-373)

**Current code (lines 348-365):**
```python
        botConfig = self.configManager.getBotConfig()

        appBuilder = (
            Application.builder()
            .token(self.botToken)
            # .concurrent_updates(PerTopicUpdateProcessor(128))
            .post_init(self.postInit)
            .post_stop(self.postStop)
            .local_mode(botConfig.get("localMode", False))
        )

        baseUrl = botConfig.get("baseUrl", None)
        if baseUrl is not None:
            appBuilder = appBuilder.base_url(baseUrl)
            logger.info(f"Base URL set to {baseUrl}")

        # Create application
        self.application = appBuilder.build()
```

**After (conceptual — not literal code):**

Between retrieving `botConfig` (line 348) and building the `appBuilder` (line 350),
insert proxy resolution:

```python
        botConfig = self.configManager.getBotConfig()

        # --- Proxy support ---
        from lib.proxy import buildHttpxClientKwargs, maskedProxyUrl, resolveProxyConfig

        proxyConfig = resolveProxyConfig(self.configManager.getProxyConfig(), botConfig)
        proxyKwargs = buildHttpxClientKwargs(proxyConfig)
        # --- End proxy support ---

        appBuilder = (
            Application.builder()
            .token(self.botToken)
            .post_init(self.postInit)
            .post_stop(self.postStop)
            .local_mode(botConfig.get("localMode", False))
        )

        # Apply proxy to both the main HTTP client and the get_updates client
        if proxyKwargs:
            import httpx
            httpxClient = httpx.AsyncClient(**proxyKwargs)
            getUpdatesClient = httpx.AsyncClient(**proxyKwargs)
            appBuilder = appBuilder.http_client(httpxClient).get_updates_http_client(getUpdatesClient)
            logger.info(f"Proxy enabled for Telegram bot: {maskedProxyUrl(proxyConfig)}")

        baseUrl = botConfig.get("baseUrl", None)
        ...
```

**IMPORTANT — Imports:** Per AGENTS.md rules, imports go at the top of the file,
not inside methods. The `from lib.proxy import ...` must be added to the
top-level imports of `internal/bot/telegram/application.py`. The only exception
is `httpx_socks` inside `lib/proxy.py` which is a conditional import to handle
the optional SOCKS5 dependency.

Add to imports section (after line 29):
```python
from lib.proxy import buildHttpxClientKwargs, maskedProxyUrl, resolveProxyConfig
```

**Lifecycle concern:** When passing a custom `httpx.AsyncClient` to
`python-telegram-bot`, the library manages its lifecycle — it calls
`client.aclose()` during shutdown. Two separate client instances are needed
(one for regular requests, one for polling) because `python-telegram-bot`
closes them independently. Verify this behavior with a quick test during
Phase 2.

### 5.2 Max Messenger Client

**Files:**
- `lib/max_bot/client.py` — `MaxBotClient.__init__()` (line 117), `_getHttpClient()` (line 175)
- `internal/bot/max/application.py` — `_runPolling()` (line 290)

**Change 1: `lib/max_bot/client.py` — Constructor**

Current `__slots__` (lines 105-115):
```python
    __slots__ = (
        "accessToken",
        "baseUrl",
        "timeout",
        "maxRetries",
        "retryBackoffFactor",
        "_httpClient",
        "_pollingTask",
        "_isPolling",
        "_myInfo",
    )
```

Add `"_proxyKwargs"` to `__slots__`.

Current `__init__` signature (lines 117-124):
```python
    def __init__(
        self,
        accessToken: str,
        baseUrl: str = API_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        maxRetries: int = MAX_RETRIES,
        retryBackoffFactor: float = RETRY_BACKOFF_FACTOR,
    ) -> None:
```

Add parameter:
```python
        proxyKwargs: Optional[Dict[str, Any]] = None,
```

Store in constructor body (after line 148):
```python
        self._proxyKwargs: Dict[str, Any] = proxyKwargs or {}
```

**Change 2: `lib/max_bot/client.py` — `_getHttpClient()`**

Current `httpx.AsyncClient(...)` call (lines 188-195):
```python
            httpClient = httpx.AsyncClient(
                base_url=self.baseUrl,
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "User-Agent": f"Gromozeka/{VERSION}",
                },
                # params={"v": "0.0.1"},
            )
```

Spread proxy kwargs:
```python
            httpClient = httpx.AsyncClient(
                **self._proxyKwargs,
                base_url=self.baseUrl,
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "User-Agent": f"Gromozeka/{VERSION}",
                },
            )
```

**Change 3: Caller — `internal/bot/max/application.py`**

Current `MaxBotClient` construction (line 290):
```python
        self.maxBot = libMax.MaxBotClient(self.botToken)
```

After:
```python
        from lib.proxy import buildHttpxClientKwargs, maskedProxyUrl, resolveProxyConfig

        botConfig = self.configManager.getBotConfig()
        proxyConfig = resolveProxyConfig(self.configManager.getProxyConfig(), botConfig)
        proxyKwargs = buildHttpxClientKwargs(proxyConfig)
        if proxyConfig:
            logger.info(f"Proxy enabled for Max bot: {maskedProxyUrl(proxyConfig)}")

        self.maxBot = libMax.MaxBotClient(self.botToken, proxyKwargs=proxyKwargs)
```

Again, the `from lib.proxy import ...` must be at the top of the file (after
line 20), not inside the method.

### 5.3 OpenAI-Compatible Providers — Main Client

**Files:**
- `lib/ai/manager.py` — `LLMManager._initProviders()` (line 92)
- `lib/ai/providers/basic_openai_provider.py` — `BasicOpenAIProvider._initClient()` (line 946)

**Strategy:** Inject the global proxy dict into each provider's config at
registration time (Option A from the discussion draft). The manager already owns
the config dict — injecting one more key is minimal, clean, and keeps `lib/`
free of `internal/` imports.

**Change 1: `lib/ai/manager.py` — `_initProviders()`**

The `LLMManager` is constructed at `main.py:60-63` with
`self.configManager.getModelsConfig()`. The proxy config is NOT in the models
config — it's a separate top-level `[proxy]` section. So `LLMManager` needs
the proxy config passed in.

**Option:** Add a `proxyConfig` parameter to `LLMManager.__init__()`.

Current (line 67):
```python
    def __init__(self, config: Dict[str, Any], *, statsStorage: Optional[StatsStorage] = None) -> None:
```

After:
```python
    def __init__(
        self,
        config: Dict[str, Any],
        *,
        statsStorage: Optional[StatsStorage] = None,
        proxyConfig: Optional[Dict[str, Any]] = None,
    ) -> None:
```

Store it:
```python
        self._proxyConfig: Dict[str, Any] = proxyConfig or {}
```

In `_initProviders()`, inject into each provider config (before line 125):
```python
                # Inject global proxy config so providers can resolve their own proxy
                provider_config["_globalProxy"] = self._proxyConfig
```

**Change 2: Caller — `main.py:60-63`**

Current:
```python
        self.llmManager = LLMManager(
            self.configManager.getModelsConfig(),
            statsStorage=llmStatsStorage,
        )
```

After:
```python
        self.llmManager = LLMManager(
            self.configManager.getModelsConfig(),
            statsStorage=llmStatsStorage,
            proxyConfig=self.configManager.getProxyConfig(),
        )
```

**Change 3: `lib/ai/providers/basic_openai_provider.py` — `_initClient()`**

Current (lines 958-969):
```python
        try:
            api_key = self._getApiKey()
            base_url = self._getBaseUrl()

            # Prepare client parameters
            client_params: Dict[str, Any] = {
                "api_key": api_key,
                "base_url": base_url,
            }
            client_params.update(self._getClientParams())

            self._client = openai.AsyncOpenAI(**client_params)
```

After — insert proxy resolution between building `client_params` and creating
the client:

```python
        try:
            api_key = self._getApiKey()
            base_url = self._getBaseUrl()

            client_params: Dict[str, Any] = {
                "api_key": api_key,
                "base_url": base_url,
            }
            client_params.update(self._getClientParams())

            # Proxy support: resolve from provider config + injected global proxy
            proxyConfig = resolveProxyConfig(
                self.config.get("_globalProxy", {}),
                self.config,
            )
            if proxyConfig:
                proxyKwargs = buildHttpxClientKwargs(proxyConfig)
                client_params["http_client"] = httpx.AsyncClient(**proxyKwargs)
                logger.info(
                    f"{self.__class__.__name__} using proxy: {maskedProxyUrl(proxyConfig)}"
                )

            self._client = openai.AsyncOpenAI(**client_params)
```

Add to top-of-file imports (the file already imports `httpx` at line 28):
```python
from lib.proxy import buildHttpxClientKwargs, maskedProxyUrl, resolveProxyConfig
```

### 5.4 Image Download — `BasicOpenAIModel._generateImageViaImagesApi()`

**File:** `lib/ai/providers/basic_openai_provider.py`  
**Method:** `_generateImageViaImagesApi()`, line 826

Current (lines 826-829):
```python
                async with httpx.AsyncClient(timeout=30.0) as client:
                    fetchResponse = await client.get(imageUrl)
                    fetchResponse.raise_for_status()
                    mediaData = fetchResponse.content
```

The model has access to `self.provider` (set in `AbstractModel.__init__` at
`lib/ai/abstract.py:106`), and the provider has `self.config` which now
contains `_globalProxy`. So the model can resolve proxy:

```python
                proxyConfig = resolveProxyConfig(
                    self.provider.config.get("_globalProxy", {}),
                    self.provider.config,
                )
                proxyKwargs = buildHttpxClientKwargs(proxyConfig)
                async with httpx.AsyncClient(**proxyKwargs, timeout=30.0) as client:
                    fetchResponse = await client.get(imageUrl)
                    fetchResponse.raise_for_status()
                    mediaData = fetchResponse.content
```

No new imports needed — the proxy imports are already added at the top of
`basic_openai_provider.py` in section 5.3.

### 5.5 OpenRouter `listRemoteModels()`

**File:** `lib/ai/providers/openrouter_provider.py`  
**Method:** `OpenrouterProvider.listRemoteModels()`, line 290

Current (lines 290-296):
```python
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
```

After:
```python
            proxyConfig = resolveProxyConfig(
                self.config.get("_globalProxy", {}),
                self.config,
            )
            proxyKwargs = buildHttpxClientKwargs(proxyConfig)
            async with httpx.AsyncClient(**proxyKwargs, timeout=30) as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
```

Add to top-of-file imports (after line 50):
```python
from lib.proxy import buildHttpxClientKwargs, resolveProxyConfig
```

### 5.6 Yandex Search Client

**File:** `lib/yandex_search/client.py`  
**Constructor:** `YandexSearchClient.__init__()` (line 106)  
**HTTP call:** `_makeRequest()` (line 354)

**Change 1: Constructor**

Add `"_proxyKwargs"` to `__slots__` (between lines 92-102).

Add parameter to `__init__` (after `rateLimiterQueue`, line 115):
```python
        proxyKwargs: Optional[Dict[str, Any]] = None,
```

Store (after line 175):
```python
        self._proxyKwargs: Dict[str, Any] = proxyKwargs or {}
```

**Change 2: `_makeRequest()`**

Current (line 354):
```python
            async with httpx.AsyncClient(timeout=self.requestTimeout) as session:
```

After:
```python
            async with httpx.AsyncClient(**self._proxyKwargs, timeout=self.requestTimeout) as session:
```

**Change 3: Caller — `internal/bot/common/handlers/yandex_search.py`**

In `YandexSearchHandler.__init__()` (lines 109-121), the `YandexSearchClient`
is constructed. Add proxy resolution before construction:

```python
        # Resolve proxy for Yandex Search
        proxyConfig = resolveProxyConfig(self.configManager.getProxyConfig(), ysConfig)
        proxyKwargs = buildHttpxClientKwargs(proxyConfig)
        if proxyConfig:
            logger.info(f"Proxy enabled for Yandex Search: {maskedProxyUrl(proxyConfig)}")

        self.yandexSearchClient = YandexSearchClient(
            apiKey=ysConfig["api-key"],
            ...  # existing args unchanged
            proxyKwargs=proxyKwargs,
        )
```

Add to imports at top of `yandex_search.py` (after line 31):
```python
from lib.proxy import buildHttpxClientKwargs, maskedProxyUrl, resolveProxyConfig
```

### 5.7 Web-Fetch — `YandexSearchHandler._downloadUrl()`

**File:** `internal/bot/common/handlers/yandex_search.py`  
**Method:** `_downloadUrl()` (line 469)

This method is in the same handler class as section 5.6. The proxy resolution
is already done in `__init__()` (section 5.6 above). Store the proxyKwargs as
an instance attribute:

```python
        self._webFetchProxyKwargs = proxyKwargs  # Same proxy as Yandex Search
```

Current `_downloadUrl()` (lines 469-481):
```python
            async with httpx.AsyncClient(
                http2=True,
                timeout=httpx.Timeout(60),
                follow_redirects=True,
                max_redirects=5,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; MyWebScraper/1.0)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru,en-US,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate",
                    # TODO: add proxy support via config
                },
            ) as client:
```

After — spread proxy kwargs and remove the TODO:
```python
            async with httpx.AsyncClient(
                **self._webFetchProxyKwargs,
                http2=True,
                timeout=httpx.Timeout(60),
                follow_redirects=True,
                max_redirects=5,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; MyWebScraper/1.0)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru,en-US,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate",
                },
            ) as client:
```

**SOCKS5 + HTTP/2 caveat:** When `type = "socks5"`, `buildHttpxClientKwargs`
returns `{"transport": AsyncProxyTransport(...)}`. Custom transports and
`http2=True` are incompatible in httpx — `http2` requires `httpcore.AsyncHTTPProxy`
or the built-in transport. If SOCKS5 is configured, the implementer must
conditionally disable `http2`:

```python
            useHttp2 = "transport" not in self._webFetchProxyKwargs
            async with httpx.AsyncClient(
                **self._webFetchProxyKwargs,
                http2=useHttp2,
                ...
            ) as client:
```

### 5.8 OpenWeatherMap Client

**File:** `lib/openweathermap/client.py`  
**Constructor:** `OpenWeatherMapClient.__init__()` (line 88)  
**HTTP call:** `_makeRequest()` (line 453)

**Change 1: Constructor**

The class does NOT use `__slots__`. Add parameter:

```python
    def __init__(
        self,
        apiKey: str,
        ...  # existing params
        rateLimiterQueue: str = "openweathermap",
        proxyKwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
```

Store:
```python
        self._proxyKwargs: Dict[str, Any] = proxyKwargs or {}
```

**Change 2: `_makeRequest()`**

Current (line 453):
```python
            async with httpx.AsyncClient(timeout=self.requestTimeout) as session:
```

After:
```python
            async with httpx.AsyncClient(**self._proxyKwargs, timeout=self.requestTimeout) as session:
```

**Change 3: Caller — `internal/bot/common/handlers/weather.py`**

In `WeatherHandler.__init__()` (lines 76-95), the `OpenWeatherMapClient` is
constructed. Add proxy resolution before construction:

```python
        # Resolve proxy
        proxyConfig = resolveProxyConfig(self.configManager.getProxyConfig(), openWeatherMapConfig)
        owmProxyKwargs = buildHttpxClientKwargs(proxyConfig)
        if proxyConfig:
            logger.info(f"Proxy enabled for OpenWeatherMap: {maskedProxyUrl(proxyConfig)}")
```

Pass `proxyKwargs=owmProxyKwargs` to `OpenWeatherMapClient(...)`.

Add to imports at top of `weather.py`:
```python
from lib.proxy import buildHttpxClientKwargs, maskedProxyUrl, resolveProxyConfig
```

### 5.9 Geocode Maps Client

**File:** `lib/geocode_maps/client.py`  
**Constructor:** `GeocodeMapsClient.__init__()` (line 118)  
**HTTP call:** `_makeRequest()` (line 479)

**Change 1: Constructor**

Add `"_proxyKwargs"` to `__slots__` (between lines 102-114).

Add parameter to `__init__` (after `rateLimiterQueue`, line 129):
```python
        proxyKwargs: Optional[Dict[str, Any]] = None,
```

Store (after line 161):
```python
        self._proxyKwargs: Dict[str, Any] = proxyKwargs or {}
```

**Change 2: `_makeRequest()`**

Current (line 479):
```python
            async with httpx.AsyncClient(timeout=self.requestTimeout) as session:
```

After:
```python
            async with httpx.AsyncClient(**self._proxyKwargs, timeout=self.requestTimeout) as session:
```

**Change 3: Caller — `internal/bot/common/handlers/weather.py`**

In `WeatherHandler.__init__()` (lines 102-128), the `GeocodeMapsClient` is
constructed. Add proxy resolution:

```python
        geocodeMapsConfig = self.configManager.getGeocodeMapsConfig()
        if geocodeMapsConfig.get("enabled"):
            geocodeProxyConfig = resolveProxyConfig(
                self.configManager.getProxyConfig(), geocodeMapsConfig
            )
            geocodeProxyKwargs = buildHttpxClientKwargs(geocodeProxyConfig)
            if geocodeProxyConfig:
                logger.info(f"Proxy enabled for Geocode Maps: {maskedProxyUrl(geocodeProxyConfig)}")
            ...
            self.geocodeMapsClient = GeocodeMapsClient(
                ...  # existing args
                proxyKwargs=geocodeProxyKwargs,
            )
```

### 5.10 Summary: Config Flow Per Service

| Service | Config source | Caller (constructs client) | Client constructor | HTTP call site |
|---|---|---|---|---|
| Telegram bot | `configManager.getBotConfig()` | `TelegramBotApplication.run()` at `application.py:340` | `Application.builder().http_client(...)` | internal to `python-telegram-bot` |
| Max Messenger | `configManager.getBotConfig()` | `MaxBotApplication._runPolling()` at `application.py:290` | `MaxBotClient.__init__()` at `client.py:117` | `_getHttpClient()` at `client.py:188` |
| OpenAI providers | `_globalProxy` injected by `LLMManager._initProviders()` | `BasicOpenAIProvider.__init__()` at `basic_openai_provider.py:888` | `_initClient()` at `basic_openai_provider.py:946` | via `openai.AsyncOpenAI(http_client=...)` |
| Image download | same `_globalProxy` via `self.provider.config` | in-method at `basic_openai_provider.py:826` | ephemeral `httpx.AsyncClient` | same line |
| OpenRouter list | same `_globalProxy` via `self.config` | in-method at `openrouter_provider.py:290` | ephemeral `httpx.AsyncClient` | same line |
| Yandex Search | `configManager.getYandexSearchConfig()` | `YandexSearchHandler.__init__()` at `yandex_search.py:109` | `YandexSearchClient.__init__()` at `client.py:106` | `_makeRequest()` at `client.py:354` |
| Web-fetch | same as Yandex Search | same handler | in-method at `yandex_search.py:469` | same line |
| OpenWeatherMap | `configManager.getOpenWeatherMapConfig()` | `WeatherHandler.__init__()` at `weather.py:76` | `OpenWeatherMapClient.__init__()` at `client.py:88` | `_makeRequest()` at `client.py:453` |
| Geocode Maps | `configManager.getGeocodeMapsConfig()` | `WeatherHandler.__init__()` at `weather.py:102` | `GeocodeMapsClient.__init__()` at `client.py:118` | `_makeRequest()` at `client.py:479` |

---

## 6. SOCKS5 Dependency

### 6.1 Package

Add to `requirements.txt` (after `httpx-sse==0.4.3` on line 29):

```
httpx-socks[asyncio]>=0.10.0
```

The `[asyncio]` extra installs `python-socks[asyncio]` which provides the
async transport needed by `AsyncProxyTransport`.

### 6.2 Conditional Import Pattern in `lib/proxy.py`

The `httpx_socks` import is **only** inside `buildHttpxClientKwargs()` and only
when `proxyConfig["type"] == "socks5"`. This is the one place where an
in-function import is acceptable (it's a conditional/optional dependency, not a
cyclic dependency workaround):

```python
def buildHttpxClientKwargs(proxyConfig: Optional[ProxyConfig]) -> Dict[str, Any]:
    if proxyConfig is None:
        return {}

    url = buildProxyUrl(proxyConfig)
    proxyType = proxyConfig.get("type", "http")

    if proxyType == "socks5":
        try:
            from httpx_socks import AsyncProxyTransport
        except ImportError:
            raise ImportError(
                "httpx-socks[asyncio] is required for SOCKS5 proxy support. "
                "Install it with: pip install 'httpx-socks[asyncio]>=0.10.0'"
            )
        transport = AsyncProxyTransport.from_url(url)
        return {"transport": transport}
    else:
        return {"proxy": url}
```

**AGENTS.md note:** AGENTS.md says "Do not add imports inside of methods or
functions" but carves out an exception for cyclic dependencies and unavoidable
cases. This is an unavoidable case: `httpx_socks` is an optional dependency
that should not be imported at module level (it would crash if not installed
and only HTTP proxies are used). Document this exception with a comment in the
code.

### 6.3 `AsyncProxyTransport` Construction

`AsyncProxyTransport.from_url(url)` accepts a URL string in the format
`socks5://[user:password@]host:port`. This is exactly what `buildProxyUrl()`
produces.

The returned transport object is then passed as `transport=` to
`httpx.AsyncClient(transport=transport)`.

**Limitation:** When using `transport=`, the `http2=True` flag on
`httpx.AsyncClient` is ignored / incompatible. Only the web-fetch client in
`yandex_search.py:469` currently uses `http2=True`. See section 5.7 for the
mitigation.

---

## 7. Implementation Phases

Each phase is a self-contained PR that can be reviewed and merged independently.
All phases include `make format lint` before and after, and `make test` after.

### Phase 1: Foundation

**Scope:**
1. Create `lib/proxy.py` with all 4 functions + types (section 3).
2. Create `configs/00-defaults/proxy.toml` (section 2.1).
3. Add `getProxyConfig()` to `internal/config/manager.py` (section 4).
4. Create `tests/lib/test_proxy.py` with full unit test suite (section 8.1).

**Depends on:** Nothing.  
**Verification:** `make format lint && make test`  
**Expected test impact:** Zero — no existing behavior changes; proxy defaults
to disabled.

### Phase 2: Wire Bot Platforms (Telegram + Max)

**Scope:**
1. Modify `internal/bot/telegram/application.py` — proxy in `run()` (section 5.1).
2. Modify `lib/max_bot/client.py` — add `proxyKwargs` to constructor and `_getHttpClient()` (section 5.2).
3. Modify `internal/bot/max/application.py` — resolve and pass proxy (section 5.2).
4. Add `use-proxy = false` to `configs/00-defaults/bot-defaults.toml` (section 2.2).

**Depends on:** Phase 1.  
**Verification:** `make format lint && make test`. Manual test with a local
HTTP proxy (e.g., `mitmproxy`) to confirm traffic routes through it.  
**Expected test impact:** Zero — `use-proxy` defaults to `false`.

### Phase 3: Wire OpenAI Providers

**Scope:**
1. Modify `lib/ai/manager.py` — add `proxyConfig` param, inject `_globalProxy` (section 5.3).
2. Modify `main.py` — pass `proxyConfig` to `LLMManager` (section 5.3).
3. Modify `lib/ai/providers/basic_openai_provider.py` — proxy in `_initClient()` (section 5.3) and `_generateImageViaImagesApi()` (section 5.4).
4. Modify `lib/ai/providers/openrouter_provider.py` — proxy in `listRemoteModels()` (section 5.5).
5. Add commented-out `use-proxy = false` examples to `configs/00-defaults/providers.toml` (section 2.3).

**Depends on:** Phase 1.  
**Verification:** `make format lint && make test`. Verify with
`--print-config` that `_globalProxy` is not leaked into printed config
(it shouldn't be — it's injected programmatically, not from TOML).  
**Expected test impact:** Zero — proxy defaults to disabled. The `_globalProxy`
injection adds a harmless extra key to provider configs that tests may see,
but it's ignored when proxy is off.

### Phase 4: Wire Yandex Search + Web-Fetch

**Scope:**
1. Modify `lib/yandex_search/client.py` — add `proxyKwargs` (section 5.6).
2. Modify `internal/bot/common/handlers/yandex_search.py` — resolve proxy, pass to client and `_downloadUrl()` (sections 5.6, 5.7). Remove `TODO: add proxy support via config` comment at line 480.
3. Add `use-proxy = false` to `[yandex-search]` in `configs/00-defaults/00-config.toml` (section 2.4).

**Depends on:** Phase 1.  
**Verification:** `make format lint && make test`.  
**Expected test impact:** Zero.

### Phase 5: Wire OpenWeatherMap + Geocode Maps

**Scope:**
1. Modify `lib/openweathermap/client.py` — add `proxyKwargs` (section 5.8).
2. Modify `lib/geocode_maps/client.py` — add `proxyKwargs` (section 5.9).
3. Modify `internal/bot/common/handlers/weather.py` — resolve proxy for both clients (sections 5.8, 5.9).
4. Add `use-proxy = false` to `[openweathermap]` and `[geocode-maps]` in `configs/00-defaults/00-config.toml` (section 2.4).

**Depends on:** Phase 1.  
**Verification:** `make format lint && make test`.  
**Expected test impact:** Zero.

### Phase 6: SOCKS5 Dependency + Final Docs

**Scope:**
1. Add `httpx-socks[asyncio]>=0.10.0` to `requirements.txt` (section 6.1).
2. Run `make install` to update venv.
3. Add SOCKS5 integration tests to `tests/lib/test_proxy.py` (section 8.1).
4. Test SOCKS5 + `http2=True` incompatibility mitigation (section 5.7).
5. Update all documentation per section 10.

**Depends on:** Phases 1-5.  
**Verification:** `make install && make format lint && make test`.

---

## 8. Testing Strategy

### 8.1 Unit Tests: `tests/lib/test_proxy.py`

New file. Test the 4 public functions in `lib/proxy.py`.

**`resolveProxyConfig()` test cases:**

| Test case | globalProxy | serviceConfig | Expected |
|---|---|---|---|
| Master switch off | `{"enabled": False, "address": "http://p:80"}` | `{"use-proxy": True}` | `None` |
| Empty global | `{}` | `{"use-proxy": True}` | `None` |
| Service not opted in | `{"enabled": True, "address": "http://p:80"}` | `{}` | `None` |
| Service use-proxy=False | `{"enabled": True, "address": "http://p:80"}` | `{"use-proxy": False}` | `None` |
| Global proxy, service opted in | `{"enabled": True, "type": "http", "address": "http://p:80"}` | `{"use-proxy": True}` | `ProxyConfig(type="http", address="http://p:80", ...)` |
| Service override | `{"enabled": True, "address": "http://p:80"}` | `{"use-proxy": True, "proxy-override": {"address": "http://other:9090"}}` | `ProxyConfig(address="http://other:9090", ...)` |
| Override with empty address (fall through) | `{"enabled": True, "address": "http://p:80"}` | `{"use-proxy": True, "proxy-override": {"address": ""}}` | `ProxyConfig(address="http://p:80", ...)` |
| Override inherits type from global | `{"enabled": True, "type": "socks5", "address": "socks5://p:1080"}` | `{"use-proxy": True, "proxy-override": {"address": "socks5://other:1080"}}` | `ProxyConfig(type="socks5", ...)` |
| Override overrides type | `{"enabled": True, "type": "http", "address": "http://p:80"}` | `{"use-proxy": True, "proxy-override": {"type": "socks5", "address": "socks5://o:1080"}}` | `ProxyConfig(type="socks5", ...)` |
| Global enabled but address empty | `{"enabled": True, "address": ""}` | `{"use-proxy": True}` | `None` (with warning) |
| Missing type defaults to http | `{"enabled": True, "address": "http://p:80"}` | `{"use-proxy": True}` | `ProxyConfig(type="http", ...)` |
| Credentials from global | `{"enabled": True, "address": "http://p:80", "user": "u", "password": "pw"}` | `{"use-proxy": True}` | `ProxyConfig(user="u", password="pw", ...)` |
| Override inherits credentials | `{"enabled": True, "address": "http://p:80", "user": "u", "password": "pw"}` | `{"use-proxy": True, "proxy-override": {"address": "http://o:80"}}` | `ProxyConfig(user="u", password="pw", ...)` |
| Override overrides credentials | `{"enabled": True, "address": "http://p:80", "user": "u", "password": "pw"}` | `{"use-proxy": True, "proxy-override": {"address": "http://o:80", "user": "u2", "password": "pw2"}}` | `ProxyConfig(user="u2", password="pw2", ...)` |

**`buildProxyUrl()` test cases:**

| Test case | ProxyConfig | Expected |
|---|---|---|
| HTTP no auth | `{"type": "http", "address": "http://p:80", "user": "", "password": ""}` | `"http://p:80"` |
| HTTP with auth | `{"type": "http", "address": "http://p:80", "user": "u", "password": "pw"}` | `"http://u:pw@p:80"` |
| SOCKS5 with auth | `{"type": "socks5", "address": "socks5://p:1080", "user": "u", "password": "pw"}` | `"socks5://u:pw@p:1080"` |
| Special chars in password | `{"type": "http", "address": "http://p:80", "user": "u", "password": "p@ss:w/d"}` | URL-safe handling (may need `quote()`) |

**`maskedProxyUrl()` test cases:**

| Test case | Expected |
|---|---|
| No auth | `"http://p:80"` |
| With auth | `"http://u:***@p:80"` |

**`buildHttpxClientKwargs()` test cases:**

| Test case | ProxyConfig | Expected |
|---|---|---|
| None | `None` | `{}` |
| HTTP | `{"type": "http", ...}` | `{"proxy": "http://..."}` |
| SOCKS5 | `{"type": "socks5", ...}` | `{"transport": <AsyncProxyTransport>}` |
| SOCKS5 without httpx-socks | `{"type": "socks5", ...}` (mock import failure) | `raises ImportError` |

### 8.2 Integration Tests

Not strictly required for Phase 1-5, but recommended for Phase 6:

- Mock HTTP proxy: Use `pytest-httpserver` or a minimal `httpx.MockTransport`
  to verify that a service configured with proxy actually sends requests
  through it.
- Each wired service should have at least one test that constructs the client
  with `proxyKwargs={"proxy": "http://mock:8080"}` and verifies the kwarg
  is passed to `httpx.AsyncClient`.

### 8.3 Existing Tests — Impact Assessment

**No existing tests should break.** Rationale:

- All proxy config defaults to `enabled = false` / `use-proxy = false`.
- `resolveProxyConfig()` returns `None` when proxy is disabled.
- `buildHttpxClientKwargs(None)` returns `{}`.
- Spreading `**{}` into `httpx.AsyncClient(...)` is a no-op.
- The `proxyKwargs` parameter on client constructors defaults to `None`.
- `LLMManager.__init__` has `proxyConfig=None` default.
- The `_globalProxy` key injected into provider configs is ignored by
  all existing code paths.

The only risk is if tests create `OpenWeatherMapClient(apiKey=..., extra=...)`
positionally instead of keyword — but scanning shows all test constructors use
keyword args. The new `proxyKwargs` parameter is keyword-only (after existing
kwargs with defaults), so positional arg order is preserved.

---

## 9. Risks & Mitigations

### Risk 1: `python-telegram-bot` Client Lifecycle

**Likelihood:** Medium  
**Impact:** High (resource leak / connection errors)  
**Description:** When we pass custom `httpx.AsyncClient` instances to
`python-telegram-bot`'s builder via `.http_client()` and
`.get_updates_http_client()`, we transfer ownership of the client lifecycle.
If `python-telegram-bot` does NOT close these clients on shutdown, we leak
connections.  
**Mitigation:** (a) Read `python-telegram-bot` source to confirm it calls
`aclose()` on provided clients during `Application.shutdown()`. (b) If it
doesn't, close the clients in `TelegramBotApplication.postStop()` (line 320).
(c) Create two separate `httpx.AsyncClient` instances — one for API calls, one
for polling — because the library closes them independently.

### Risk 2: SOCKS5 + HTTP/2 Incompatibility

**Likelihood:** High (known httpx limitation)  
**Impact:** Low (affects only web-fetch with SOCKS5)  
**Description:** `httpx.AsyncClient(transport=..., http2=True)` raises or
silently ignores `http2` when a custom transport is provided. Only
`_downloadUrl()` in `yandex_search.py` uses `http2=True`.  
**Mitigation:** Conditionally disable `http2` when a `transport` key is
present in proxyKwargs (see section 5.7). Log a warning:
`"HTTP/2 disabled for web-fetch: SOCKS5 transport does not support HTTP/2"`.

### Risk 3: Credential Leaks in Logs

**Likelihood:** Medium  
**Impact:** High (security)  
**Description:** Proxy URLs with embedded credentials could be logged by httpx,
`python-telegram-bot`, or our own debug logging.  
**Mitigation:** (a) `lib/proxy.py` provides `maskedProxyUrl()` — all logging
in caller code must use this, never the raw URL. (b) The httpx library logs at
DEBUG level — our production config sets httpx to WARNING (`main.py:31`:
`logging.getLogger("httpx").setLevel(logging.WARNING)`), which suppresses
connection-level debug logs. (c) Code review must check that no call site logs
the return value of `buildProxyUrl()` or the `proxy=` kwarg.

### Risk 4: `openai` Library Custom `http_client` Support

**Likelihood:** Low  
**Impact:** Medium (LLM calls would fail through proxy)  
**Description:** `openai.AsyncOpenAI(http_client=...)` is documented to accept
a custom `httpx.AsyncClient`, but edge cases (streaming, file uploads, retries)
might not respect the custom client.  
**Mitigation:** (a) The `openai` library (v2.36.0 in `requirements.txt`) has
stable `http_client` support. (b) Run a quick manual test with a proxy during
Phase 3: make a streaming completion call, verify traffic routes through the
proxy. (c) If issues arise, fall back to setting `HTTPS_PROXY` env var as a
last resort (but this affects all services globally).

### Risk 5: Hot-Reload Expectations

**Likelihood:** Low  
**Impact:** Low (operator confusion)  
**Description:** Operators might expect proxy config changes to take effect
without restarting the bot.  
**Mitigation:** Document clearly that proxy config is loaded at startup only.
Add a comment in `proxy.toml` and in `docs/developer-guide.md`.

### Risk 6: Ephemeral Client Overhead with SOCKS5

**Likelihood:** Low  
**Impact:** Low (minor performance)  
**Description:** Services that create a new `httpx.AsyncClient` per request
(Yandex Search, OpenWeatherMap, Geocode Maps, web-fetch, `listRemoteModels`,
image download) will also create a new `AsyncProxyTransport` per request when
using SOCKS5. Each transport establishes a new SOCKS5 handshake.  
**Mitigation:** Not a v1 concern — these services make infrequent requests.
If profiling shows SOCKS5 handshake overhead is significant, cache the
transport at the client level (store it alongside `_proxyKwargs` and reuse).

---

## 10. Documentation Impact

After all phases are complete, the following docs need updating. Load the
`update-project-docs` skill when executing the documentation pass.

| Doc | Section(s) to Update | What Changes |
|---|---|---|
| **`configs/00-defaults/proxy.toml`** | New file | Created in Phase 1 |
| **`docs/llm/configuration.md`** | Section 2 (Config Sections Reference) | Add `[proxy]` section reference. Add `use-proxy` and `proxy-override` to each service section. Add `getProxyConfig()` to ConfigManager methods table. |
| **`docs/llm/libraries.md`** | New section for `lib/proxy` | Add `lib/proxy` module reference with all 4 public functions, `ProxyConfig` TypedDict, and usage examples. |
| **`docs/llm/libraries.md`** | Section 5 (lib/max_bot) | Note new `proxyKwargs` parameter on `MaxBotClient.__init__()`. |
| **`docs/llm/libraries.md`** | Section 7 (lib/openweathermap) | Note new `proxyKwargs` parameter on `OpenWeatherMapClient.__init__()`. |
| **`docs/llm/libraries.md`** | Section 8 (lib/geocode_maps) | Note new `proxyKwargs` parameter on `GeocodeMapsClient.__init__()`. |
| **`docs/llm/libraries.md`** | Section 1 (lib/ai) | Note `_globalProxy` injection pattern in `LLMManager` and proxy support in `BasicOpenAIProvider._initClient()`. |
| **`docs/llm/services.md`** | LLMService section | Note that proxy config flows through `LLMManager` → providers → models. |
| **`docs/llm/handlers.md`** | YandexSearchHandler section | Note proxy support, resolution in `__init__`, TODO removed from `_downloadUrl()`. |
| **`docs/llm/handlers.md`** | WeatherHandler section | Note proxy support for both OpenWeatherMap and Geocode Maps clients. |
| **`docs/developer-guide.md`** | New section: "Proxy Configuration" | Operator-facing instructions: how to enable proxy, per-service overrides, SOCKS5 setup, env var substitution, restart requirement. |
| **`requirements.txt`** | After `httpx-sse` | Add `httpx-socks[asyncio]>=0.10.0` |
| **`docs/llm/index.md`** | Section 4.6 (lib/ Directory) | Add `lib/proxy.py` entry. |
| **`AGENTS.md`** | Nowhere | No changes needed — proxy is not an architectural pattern agents need to know about for general development. |
