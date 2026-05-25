# Proxy Task Memory

Durable task-specific memory for the completed proxy support work (2026-05-23).

How to use this file:
- Read it when touching `lib/proxy/`, proxy configuration, per-service proxy overrides, or HTTP client proxy wiring.
- Keep only proxy-scoped discoveries here; move repo-wide lessons back to [`../teamlead-memory.md`](../teamlead-memory.md).
- Never store secrets, tokens, `.env` values, or raw logs.

## Implementation Summary

- **Status:** IMPLEMENTED. 2373 tests passing. All review gates passed.
- **Design:** `lib/proxy/__init__.py` — `ProxyConfig` class (uses `__slots__`), `ProxyKwargs` TypedDict; `ProxyType` StrEnum; `ProxyHelper` singleton. Resolution via `ProxyConfig.fromServiceConfig()` (per-service) and `ProxyConfig.getCombined()` (merge with global). `ProxyConfig.getProxyURL(maskPassword=True)` for safe logging. `ProxyConfig.toKwargs()` for httpx kwargs.
- **Config hierarchy:** Global `[proxy]` section + per-service `use-proxy` (kebab-case) + optional `[service.proxy]` overrides. Master kill-switch `[proxy].enabled = false`.
- **Proxied services:** Telegram bot, Max client, all OpenAI-compatible AI providers, Yandex Search API, web-fetch, OpenWeatherMap, Geocode Maps, sqlink database provider.
- **Out of scope:** YC SDK (gRPC), sandbox (container networking), S3 storage (separate proxy story).
- **SOCKS5:** `httpx-socks[asyncio]>=0.10.0` in requirements.txt. Conditional import at module level.
- **Tests:** `tests/lib/test_proxy.py` — 41 tests.
- **Security:** `ProxyConfig.getProxyURL(maskPassword=True)` for logging (password -> `REDACTED`). URL building uses `quote()` for credential encoding.

## Key Files

`lib/proxy/__init__.py` (package), `lib/ai/abstract.py` (aclose), `lib/ai/providers/basic_openai_provider.py` (proxy + aclose), `internal/bot/telegram/application.py` (PTB proxy), `lib/max_bot/client.py`, `lib/openweathermap/client.py`, `lib/geocode_maps/client.py`, `lib/yandex_search/client.py`, `internal/bot/common/handlers/yandex_search.py`, `internal/bot/common/handlers/weather.py`, `internal/database/providers/sqlink.py`, `internal/database/providers/__init__.py` (sqlink proxy resolution), `main.py` (`ProxyHelper.getInstance().setGlobalProxyConfig()`).

## Proxy-Specific Conventions

- `lib/proxy` is a package (`lib/proxy/__init__.py`), not a single file. Internal modules can be added under `lib/proxy/` in the future.
- `ProxyKwargs` TypedDict for proxy kwargs (instead of generic `Dict[str, Any]`): `class ProxyKwargs(TypedDict, total=False): proxy: str; transport: Any`.
- Global proxy storage: `setGlobalProxyConfig()` called once from `main.py`; `getGlobalProxyConfig()` used by all services. No threading through constructors.
- Config key for per-service proxy overrides is `proxy` (not `proxy-override`). Example: `[bot.proxy]`, `[yandex-search.proxy]`.

## fromServiceConfig Behavior — Per-Service Override Semantics

`ProxyConfig.fromServiceConfig(data)` reads `use-proxy` and `proxy` keys from a service config dict, then delegates to `ProxyConfig.fromDict()`. The critical semantics:

- **When `use-proxy` is not present or `False`**: The service gets a ProxyConfig with `type=NONE` and `enabled=True` — meaning `getCombined()` does not fall back to global, and the service effectively runs without proxy.
- **When `use-proxy=True`** (per-service opt-in): `enabled` is read from the proxy sub-dict (`data.get("enabled") is True`). This has an important consequence:
  - If the `proxy` sub-section exists but does **not** include `enabled: true`, the resulting ProxyConfig has `enabled=False`.
  - When `enabled=False`, `getCombined()` treats this as "inherit from global" rather than applying the override.
  - **Therefore:** to apply per-service proxy override settings (different proxy type, address, etc.), the `proxy` sub-section **must** include `enabled: true`. Without it, `use-proxy=true` alone only opts the service into the global proxy, ignoring any per-service overrides.

Example — this overrides the global proxy for a service:
```toml
[openweathermap]
use-proxy = true

[openweathermap.proxy]
enabled = true    # REQUIRED for the override to take effect
type = "socks5"
address = "${OWM_PROXY_ADDRESS}"
```

Example — this opts in to global proxy but silently ignores the override:
```toml
[openweathermap]
use-proxy = true

[openweathermap.proxy]
type = "socks5"           # IGNORED because enabled is missing
address = "${OWM_PROXY_ADDRESS}"  # IGNORED
```

**This is intentional behavior** — `enabled` in the proxy sub-section is the per-service kill-switch that `getCombined()` checks. When it is absent or `False`, the service inherits the global proxy unchanged.

## __repr__ / __str__ — Password Masking

`ProxyConfig.__repr__()` (and `__str__`, which delegates to `__repr__`) masks non-empty passwords in its output. A non-empty password renders as `'***'`:

```python
>>> cfg = ProxyConfig(proxyType=ProxyType.HTTP, address="http://proxy:8080",
...                   user="user", password="secret")
>>> repr(cfg)
"ProxyConfig(proxyType='http', address='http://proxy:8080', user='user', password='***', enabled=True)"
```

When password is `None` or empty string, it renders verbatim (as `None` or `''`). This is safe for logging/debugging output while preventing accidental credential leaks through repr/str.

This is separate from `getProxyURL(maskPassword=True)` which replaces the password with `"REDACTED"` in the built URL string.

## SQLink Proxy — Lazy Resolution

`SQLinkProvider` stores the proxy config as a `ProxyConfig` object at construction time but does **not** resolve it immediately. Resolution happens lazily in `connect()`:

1. `SQLinkProvider.__init__()` accepts a `proxy: Optional[ProxyConfigDict]` kwarg and `use-proxy` from `kwargs`. These are passed to `ProxyConfig.fromDict()` to create the internal `self._proxy` object.
2. When `connect()` is called (on first query, or eagerly if `keepConnection=True`), it calls `self._proxy.getProxyURL()` to resolve the proxy URL against the global config stored in `ProxyHelper`.
3. The resolved URL is passed as the `proxy` parameter to `sqlink.asyncConnect()`.

This lazy resolution is important because:
- The global proxy config is set by `main.py` (via `ProxyHelper.getInstance().setGlobalProxyConfig()`) **before** any database connections are established — so the resolution order is correct.
- If the proxy URL were resolved in `__init__`, the global config might not yet be available.

## SQLink Proxy Config Nesting

sqlink proxy configuration lives under `[database.providers.<name>.parameters]`:

```toml
[database.providers.archive]
provider = "sqlink"

[database.providers.archive.parameters]
url = "https://sqlink.example.com"
user = "bot"
password = "${SQLINK_PASSWORD}"
database = "archive"
timeout = 30
keepConnection = true
use-proxy = true
# [database.providers.archive.parameters.proxy]
# type = "http"
# address = "${DB_PROXY_ADDRESS}"
```

The `use-proxy` key and optional `proxy` sub-table must be inside `parameters` because `getSqlProvider()` in `internal/database/providers/__init__.py` extracts `config["parameters"]` and passes it as `**parameters` to the provider constructor (`SQLinkProvider(**parameters)`). Keys placed directly under the provider block (e.g. `[database.providers.archive]`) are not forwarded to the constructor.

## Anti-Patterns Learned

- **Free-function sprawl over class-based design.** When a feature needs state (global config) and multiple operations that compose together (resolve -> merge -> build URL -> build kwargs), prefer a cohesive class with methods over a collection of module-level free functions. A class with `fromDict`/`fromServiceConfig` classmethods, `getCombined`/`getProxyURL`/`toKwargs` instance methods is clearer, more discoverable, and easier to test than four separate functions that call each other.
- **Config threading through constructors when a singleton works better.** If every service and every layer of the call chain needs the same config value, use the project's established singleton pattern (`getInstance()` / `setGlobalConfig()`) instead of adding a new parameter to every constructor.
- **Never add `__dict__` to `__slots__` as a test-mocking workaround.** Adding `"__dict__"` to `__slots__` completely defeats the purpose. Instead, mock at the class level (`patch.object(ClassName, "_method", ...)` rather than `patch.object(instance, "_method", ...)`). Class-level mocking works on slotted classes without `__dict__`.

## Complete HTTP Client Inventory (from 2026-05-23 audit)

**In scope (all need proxy):**

| # | Service | File | Library | Persistence |
|---|---------|------|---------|-------------|
| 1 | Max Messenger client | `lib/max_bot/client.py:188` | `httpx.AsyncClient` | Persistent (`self._httpClient`) |
| 2 | Telegram bot | `internal/bot/telegram/application.py:365` | `python-telegram-bot` (httpx internally) | Persistent (PTB-managed) |
| 3 | OpenAI-compatible providers | `lib/ai/providers/basic_openai_provider.py:969` | `openai.AsyncOpenAI` | Persistent (`self._client`) |
| 4 | Image download (OpenAI) | `lib/ai/providers/basic_openai_provider.py:826` | `httpx.AsyncClient` | Ephemeral |
| 5 | OpenRouter listRemoteModels | `lib/ai/providers/openrouter_provider.py:290` | `httpx.AsyncClient` | Ephemeral |
| 6 | Yandex Search API | `lib/yandex_search/client.py:354` | `httpx.AsyncClient` | Ephemeral |
| 7 | Web-fetch (yandex_search handler) | `internal/bot/common/handlers/yandex_search.py:469` | `httpx.AsyncClient` | Ephemeral |
| 8 | OpenWeatherMap | `lib/openweathermap/client.py:453` | `httpx.AsyncClient` | Ephemeral |
| 9 | Geocode Maps | `lib/geocode_maps/client.py:479` | `httpx.AsyncClient` | Ephemeral |

**Out of scope:**
- YC SDK provider (`yandex_ai_studio_sdk` -- gRPC)
- Sandbox Docker backend (`aiodocker` -- container networking)
- S3 storage backend (`boto3` -- separate proxy story)
- Aurumentation test infra (not production)
- `requests` library -- not used in production code
