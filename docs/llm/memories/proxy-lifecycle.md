# Proxy Lifecycle Management — Durable Memory

Archived notes from the proxy lifecycle management feature (completed 2026-06-26).
Read when touching `internal/services/proxy/`, `lib/proxy/` lifecycle fields,
`configs/00-defaults/proxy.toml`, or proxy call-site wiring.

## Architecture

### Design Document
- `docs/plans/proxy-lifecycle-design.md` — canonical design. 4 phases implemented.

### Key Classes

| Class | Location | Role |
|---|---|---|
| `ProxyService` | `internal/services/proxy/service.py` | Singleton. Orchestrates all proxy lifecycles. `initialize(queueService, configManager)`, `resolveProxy(serviceConfig, serviceLabel)`. |
| `ProxyLifecycle` | `internal/services/proxy/lifecycle.py` | Non-singleton. One per proxy config. Manages start/stop/restart/health-check for a single proxy process. |
| `HealthCheckType` | `lib/proxy/__init__.py` | `StrEnum` — `NONE`, `URL`, `COMMAND`. |
| `ProxyLifecycleConfigDict` | `lib/proxy/__init__.py` | `TypedDict` with 7 optional lifecycle fields. |

### Integration Points
- `QueueService` CRON_JOB: periodic health checks (~60s ticks, gated by modulo on interval).
- `QueueService` DO_EXIT: graceful shutdown of all proxy processes.
- `main.py`: `ProxyService.getInstance().initialize()` called after `setGlobalProxyConfig()`.
- Call sites migrated (4 files): `telegram/application.py`, `max/application.py`, `weather.py`, `yandex_search.py`.

### Call-Site Migration Pattern
Replace direct `ProxyConfig.fromServiceConfig()` calls with:
```python
from internal.services.proxy import ProxyService

proxyConfig = ProxyService.getInstance().resolveProxy(serviceConfig, "my-service")
```
Consumers in `lib/` remain unchanged (they can't import `internal/`).

## Gotchas

### Subprocess Management
- **Fire-and-forget must use DEVNULL**: `asyncio.create_subprocess_exec(..., stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)`. Using `PIPE` causes pipe-buffer deadlock.
- **Kill on timeout**: `asyncio.wait_for()` raises `TimeoutError` but does NOT kill the child. Always `process.kill()` + `await process.wait()` in the except block.
- **`asyncio.run()` for sync-context startup**: `GromozekBot.__init__` is synchronous. The global proxy start command bridges via `asyncio.run(lifecycle.start())`.

### Lifecycle State Flags
- `_started` flag prevents double-start. Checked via public `started` property.
- `_initialized` flag on `ProxyService` prevents double `initialize()` calls (idempotent).
- Per-service lifecycles are deferred to first CRON_JOB tick (~60s delay).
- Global lifecycle starts immediately via `asyncio.run()`.

### Health Check Gating
- CRON_JOB fires every ~60s. Health check interval is in minutes.
- Gating uses modulo: `tickCount % interval == 0`.
- URL health check goes through the proxy itself (uses `proxyConfig` to build httpx client).
- Misconfigured health check type logs warning, does not raise.

### Singleton Reset in Tests
```python
@pytest.fixture(autouse=True)
def resetProxyServiceSingleton():
    from internal.services.proxy import ProxyService
    ProxyService._instance = None
    yield
    ProxyService._instance = None
```

### TOML Key Conversion
- TOML uses kebab-case (`start-command`, `health-check-type`).
- Python uses camelCase (`startCommand`, `healthCheckType`).
- `_kebabToCamelCase()` helper in `lib/proxy/__init__.py` handles conversion in `ProxyConfig.fromDict()`.

## Files

| File | Purpose |
|---|---|
| `lib/proxy/__init__.py` | `HealthCheckType`, `ProxyLifecycleConfigDict`, `_kebabToCamelCase()`, `lifecycle` field on `ProxyConfig` |
| `internal/services/proxy/__init__.py` | Re-exports `ProxyLifecycle`, `ProxyService` |
| `internal/services/proxy/lifecycle.py` | `ProxyLifecycle` class (281 lines) |
| `internal/services/proxy/service.py` | `ProxyService` class (210 lines) |
| `configs/00-defaults/proxy.toml` | Commented-out `[proxy.lifecycle]` section |
| `tests/services/proxy/test_lifecycle.py` | 29 unit tests |
| `tests/services/proxy/test_service.py` | 9 integration tests |
