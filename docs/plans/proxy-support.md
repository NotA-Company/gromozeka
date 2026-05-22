# Proxy Support — Architectural Plan (Discussion Draft)

> **Status:** DRAFT — for team review before implementation.

## Goal

Route outbound HTTP traffic through configurable HTTP/SOCKS5 proxies. Each
service opts in with a boolean flag and can optionally override the global
proxy. No code changes to services that stay out of scope.

## Scope

| Service | Transport | In scope? |
|---|---|---|
| Telegram bot (`python-telegram-bot` / `httpx`) | HTTPS | Yes |
| Max Messenger client (`httpx`) | HTTPS | Yes |
| OpenAI-compatible AI providers (OpenRouter, YC OpenAI, Custom OpenAI) | HTTPS | Yes |
| Yandex Search client (`httpx`) | HTTPS | Yes |
| Web-fetch in yandex_search handler (`httpx`) | HTTPS | Yes |
| OpenWeatherMap client (`httpx`) | HTTPS | Yes |
| Geocode Maps client (`httpx`) | HTTPS | Yes |
| YC SDK provider (gRPC) | gRPC | No — different proxy model |
| Sandbox / Docker backend | container networking | No — too complex for v1 |

## 1. Config TOML Structure

New file `configs/00-defaults/proxy.toml`:

```toml
# Global proxy — used by any service that sets use-proxy = true
# and does not provide its own proxy-override section.
[proxy]
enabled = false      # master kill-switch; when false, NO service uses proxy
type = "http"        # "http" | "socks5"
address = ""         # e.g. "http://proxy.example.com:8080" or "socks5://proxy.example.com:1080"
user = ""            # optional — Basic Auth username
password = ""        # optional — Basic Auth password
```

Per-service opt-in is a `use-proxy` boolean added to the service's existing
config section. Per-service override is a `[service.proxy-override]`
sub-table with the same `type`/`address`/`user`/`password` keys.

Example additions to existing defaults files:

```toml
# In bot-defaults.toml
[bot]
use-proxy = false

# If the operator wants a different proxy just for Telegram:
# [bot.proxy-override]
# type = "socks5"
# address = "socks5://tg-proxy.example.com:1080"

# In providers.toml — per-provider, not global to all providers
[models.providers.openrouter]
use-proxy = false

[models.providers.yc-openai]
use-proxy = false

# In 00-config.toml
[yandex-search]
use-proxy = false

[openweathermap]
use-proxy = false

[geocode-maps]
use-proxy = false
```

Secrets (`user`, `password`, `address`) should use `${ENV_VAR}` substitution
so they never appear in committed TOML.

## 2. Shared ProxyConfig TypedDict

A single shared type so every consumer parses the same shape. Lives in a new
small module — proposed location: `lib/proxy.py`.

```python
# Pseudocode — NOT implementation code
class ProxyConfig(TypedDict, total=False):
    """Resolved proxy configuration for a single service."""
    type: str          # "http" | "socks5"
    address: str       # full URL including scheme
    user: str          # may be empty
    password: str      # may be empty
```

The module also provides two helpers:

- `resolveProxyConfig(globalProxy, serviceConfig) -> Optional[ProxyConfig]` —
  implements the resolution logic from section 3.
- `buildHttpxProxy(proxyConfig) -> Optional[str]` — turns a `ProxyConfig`
  into the value httpx expects for its `proxy=` parameter (URL string with
  embedded credentials when present, e.g.
  `socks5://user:pass@host:port`). Returns `None` when no proxy applies.

This keeps proxy logic out of every service and avoids duplicating resolution
or URL-building code.

## 3. Proxy Resolution Logic

All in `resolveProxyConfig()`:

```
1. If global [proxy].enabled is false → return None (no proxy, regardless of service flags).
2. If service.use-proxy is false (or absent) → return None.
3. If service has a [service.proxy-override] sub-section → return that override as ProxyConfig.
4. Otherwise → return global [proxy] as ProxyConfig.
```

This means the global `enabled` flag is a master kill-switch: turning it off
disables proxy everywhere without touching per-service config.

## 4. ConfigManager Changes

Add one new accessor to `internal/config/manager.py`:

```python
def getProxyConfig(self) -> Dict[str, Any]:
    """Get global proxy configuration."""
    return self.get("proxy", {})
```

The per-service `use-proxy` and `proxy-override` are already inside each
service's existing config dict (e.g. `getBotConfig()["use-proxy"]`), so no
additional accessors are needed — `resolveProxyConfig` reads them directly.

## 5. Per-Service Wiring

### 5.1 Telegram bot — `internal/bot/telegram/application.py`

**Method:** `run()` (lines 340-373).

Change: after building `appBuilder`, resolve proxy. If proxy is active,
construct `httpx.AsyncClient(proxy=proxyUrl)` and pass it via
`appBuilder.http_version("2").get_updates_http_version("2")` and the
`.http_client()` / `.get_updates_http_client()` builder methods that
`python-telegram-bot` exposes.

```
proxyConfig = resolveProxyConfig(configManager.getProxyConfig(), botConfig)
proxyUrl = buildHttpxProxy(proxyConfig)
if proxyUrl:
    httpxClient = httpx.AsyncClient(proxy=proxyUrl)
    appBuilder = appBuilder.http_client(httpxClient).get_updates_http_client(httpxClient)
```

### 5.2 Max Messenger client — `lib/max_bot/client.py`

**Method:** `__init__()` (line 117), `_getHttpClient()` (line 175).

Change: add an optional `proxy: Optional[str] = None` parameter to the
constructor. Store it. In `_getHttpClient()` pass `proxy=self._proxy` to
`httpx.AsyncClient(...)` at line 188.

The caller that constructs `MaxBotClient` (likely in
`internal/bot/max/application.py`) resolves the proxy from config and passes
the URL string.

### 5.3 OpenAI-compatible providers — `lib/ai/providers/basic_openai_provider.py`

**Method:** `_initClient()` (line 946), via `_getClientParams()` (line 934).

The provider config dict already flows through from
`LLMManager._initProviders()` → `providerTypes[providerType](provider_config)`
(manager.py:125). Each provider stores its config as `self.config`.

Change in `BasicOpenAIProvider._initClient()`: after building `client_params`,
resolve proxy from `self.config` (which contains `use-proxy` and
`proxy-override` if set). If proxy is active, create
`httpx.AsyncClient(proxy=proxyUrl)` and add `"http_client": httpxClient`
to `client_params`.

This needs the global proxy config to be available. Two options:

- **(A) Pass global proxy into provider config at registration time** — in
  `LLMManager._initProviders()`, inject `config["_globalProxy"] = ...` so
  each provider sees it. Simple, no new plumbing.
- **(B) Read global proxy from ConfigManager singleton** — providers live in
  `lib/` which shouldn't depend on `internal/`. This violates the dependency
  direction.

**Recommendation:** option (A). The manager already owns the config dict; it
can inject the global proxy sub-dict before passing to providers.

**Ephemeral clients also need proxy:**

- `OpenrouterProvider.listRemoteModels()` (openrouter_provider.py:290) —
  creates bare `httpx.AsyncClient(timeout=30)`. Add `proxy=` there, reading
  from `self.config`.
- `BasicOpenAIModel._generateImageViaImagesApi()` (basic_openai_provider.py:826) —
  ephemeral `httpx.AsyncClient(timeout=30.0)` for image download. The model
  needs access to the resolved proxy URL; it can read it from its parent
  provider (the provider already stores config).

### 5.4 Yandex Search client — `lib/yandex_search/client.py`

**Method:** `_makeRequest()` (line 354).

Change: add `proxy: Optional[str] = None` to the constructor. Pass
`proxy=self._proxy` to `httpx.AsyncClient(...)` at line 354.

Caller (in the yandex_search handler init) resolves proxy from config.

### 5.5 Web-fetch in yandex_search handler — `internal/bot/common/handlers/yandex_search.py`

**Method:** `_downloadUrl()` (line 469). Already has a TODO at line 480.

Change: resolve proxy in handler init (the handler has access to
`configManager`). Pass proxy URL into `_downloadUrl()`, which passes
`proxy=proxyUrl` to its `httpx.AsyncClient(...)`.

### 5.6 OpenWeatherMap client — `lib/openweathermap/client.py`

**Method:** `_makeRequest()` (line 453).

Constructor signature: `__init__(self, apiKey, cacheTtl, ...)`.

Change: add optional `proxy: Optional[str] = None` parameter to the
constructor. Store it. Pass `proxies=self._proxy` (or `transport=...` for
SOCKS5) to `httpx.AsyncClient(...)` at line 453.

Caller (likely in WeatherHandler init) resolves proxy from config and
passes the URL string. Same pattern as Yandex Search client (5.4).

### 5.7 Geocode Maps client — `lib/geocode_maps/client.py`

**Method:** `_makeRequest()` (line 479).

Constructor signature: `__init__(self, apiKey, ...)`.

Change: add optional `proxy: Optional[str] = None` parameter to the
constructor. Store it. Pass `proxies=self._proxy` (or `transport=...` for
SOCKS5) to `httpx.AsyncClient(...)` at line 479.

Caller (likely in GeocodeMapsHandler or wherever the client is constructed)
resolves proxy from config and passes the URL string. Same pattern as
Yandex Search client (5.4).

## 6. SOCKS5 Dependency

`httpx` does not support SOCKS5 natively. Requires one of:

| Package | Purpose | Notes |
|---|---|---|
| `httpx-socks` | SOCKS5/SOCKS4 transport for httpx | Wraps `python-socks`. Well-maintained. |
| `python-socks` | Low-level SOCKS implementation | Transitive dep of `httpx-socks`. |

With `httpx-socks` installed, usage is:

```python
from httpx_socks import AsyncProxyTransport
transport = AsyncProxyTransport.from_url("socks5://user:pass@host:port")
client = httpx.AsyncClient(transport=transport)
```

This means `buildHttpxProxy()` would return different objects for HTTP vs
SOCKS5 proxies — for HTTP it returns a plain URL string (httpx handles it
natively via `proxy=`), for SOCKS5 it returns an `AsyncProxyTransport` that
the caller passes as `transport=`. The helper API should abstract this; a
possible signature:

```python
def buildHttpxClientKwargs(proxyConfig: Optional[ProxyConfig]) -> Dict[str, Any]:
    """Return kwargs to spread into httpx.AsyncClient(...).

    For HTTP proxy: {"proxy": "http://..."}
    For SOCKS5:     {"transport": AsyncProxyTransport.from_url("socks5://...")}
    For no proxy:   {}
    """
```

Each call site then does `httpx.AsyncClient(**buildHttpxClientKwargs(proxy), timeout=..., ...)`.

**For python-telegram-bot:** its builder's `.http_client()` accepts a
pre-built `httpx.AsyncClient`, so the same approach works — build the client
with the right transport/proxy kwarg and hand it to the builder.

**For `openai.AsyncOpenAI`:** accepts `http_client=httpx.AsyncClient(...)`,
same pattern.

**Add `httpx-socks` to `requirements.txt`.** It's a no-op if only HTTP
proxies are used (the import is conditional on `type == "socks5"`).

## 7. Open Questions / Risks

1. **`python-telegram-bot` client lifecycle.** When we pass a custom
   `httpx.AsyncClient`, we own its lifecycle. Need to verify that
   `python-telegram-bot`'s shutdown path closes it, or we close it in
   `postStop()`. Needs a quick test.

2. **SOCKS5 + HTTP/2.** `httpx-socks` transport may not support HTTP/2.
   The web-fetch client in yandex_search handler currently uses `http2=True`.
   If SOCKS5 is configured and HTTP/2 is required, we may need to fall back
   to HTTP/1.1. Test before shipping.

3. **Hot-reload.** Config is loaded once at startup. Changing proxy config
   requires a restart. This is fine for v1 but worth noting.

4. **Credential logging.** Proxy URLs may contain passwords. Ensure no
   logger prints the resolved URL at INFO level. `buildHttpxClientKwargs`
   should never log the URL; callers should log "proxy enabled for service X"
   without the address.

5. **`openai` library proxy support.** Verify that `openai.AsyncOpenAI`
   correctly uses a custom `http_client` for all requests (including
   streaming). The library docs say yes, but a quick integration test is
   prudent.

6. **Ephemeral vs persistent clients.** Some services create a new
   `httpx.AsyncClient` per request (Yandex Search, OpenWeatherMap,
   Geocode Maps, web-fetch, `listRemoteModels`, image download).
   Constructing an `AsyncProxyTransport` per request may have overhead
   for SOCKS5. If this becomes a problem, cache the transport. Not a v1
   concern.

## 8. Documentation Impact

After implementation, update:

| Doc | What changes |
|---|---|
| `configs/00-defaults/proxy.toml` (new file) | Default proxy config |
| `docs/llm/configuration.md` | New `[proxy]` section, per-service `use-proxy` flag |
| `docs/llm/libraries.md` | New `lib/proxy.py` module |
| `docs/llm/services.md` | Note proxy support in Telegram/Max/LLM service descriptions |
| `docs/llm/handlers.md` | Note proxy support in yandex_search, weather, geocode handlers |
| `docs/llm/libraries.md` | Note proxy param in OpenWeatherMap/Geocode Maps/Yandex Search clients |
| `docs/developer-guide.md` | Proxy setup instructions |
| `requirements.txt` | `httpx-socks` dependency |
