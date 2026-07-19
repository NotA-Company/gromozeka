# Max API Migration

Durable notes from the Max Messenger API endpoint migration and TLS/certificate trust implementation. Read this when working on `lib/max_bot/`, `internal/bot/max/`, Max API endpoints, or TLS/SSL configuration for Max.

## Max Bot API

- **Current API endpoint**: `https://platform-api2.max.ru` — defined at `lib/max_bot/constants.py` as `API_BASE_URL`. Migrated from the deprecated `platform-api.max.ru` per `docs/archive/plans/max-api-migration.md`. The legacy endpoints (`platform-api.max.ru`, `botapi.max.ru`) are kept as comments only.
- **Deadline**: 2026-07-19 — all requests must use `platform-api2.max.ru` and trust the Минцифры (Russian Ministry of Digital Development) root CA certificate. Migration implemented June 2026.
- **Auth**: Raw access token sent as `Authorization` header (no `Bearer` prefix, no query param). This is already correct for the new API — the deprecated query-param auth never applied to this client.
- **TLS/SSL**: Custom SSL context built by `libMax.utils.buildMaxSslContext(caBundlePath)` from the `[bot].max-ca-bundle` config key. Default is `"../certs/max"` — relative to `application.root-dir` (`"storage"`), resolves to `<repo-root>/certs/max/`. The directory holds the Russian Минцифры root/intermediate PEM certs (5 files: 3 RSA + 2 GOST). The raw `caBundlePath` config value is passed directly to `MaxBotClient(caBundlePath=...)`, which builds the `ssl.SSLContext` internally via `buildMaxSslContext()`. `_getHttpClient()` conditionally passes `verify=` to `httpx.AsyncClient` only when no SOCKS5 transport is present AND a custom CA context exists (`if "transport" not in proxyKwargs and self._sslContext is not None`). When the key is empty/unset, no `verify=` is passed — httpx falls back to its default CA bundle. **SOCKS5 proxy caveat**: httpx ignores the top-level `verify=` when a custom `transport=` is supplied, so for SOCKS5 proxies (`ProxyType.SOCKS5`) the SSL context is threaded into the transport via `ProxyConfig.toKwargs(verify=self._sslContext)` (which calls `AsyncProxyTransport.from_url(url, verify=sslContext)`); the client-level `verify=` is skipped via the `"transport" not in clientKwargs` guard.
- **Polling**: Long-poll via `GET /updates` with timeout=30s, limit=100. Implemented in `MaxBotClient._pollingLoop()`. Called from `MaxBotApplication._runPolling()`. Continuous loop with no fixed interval — on update receipt or timeout, immediately polls again.
- **Webhook methods exist** in client (`setWebhook`, `deleteWebhook`, `getWebhookInfo`). `setWebhook`/`deleteWebhook` are now used by `MaxBotApplication` when `webhook-receiver.enabled = true` and `register-webhook`/`unregister-webhook` are enabled. Application uses long-polling by default; webhook mode polls local receiver's GET /updates.
- **Only 4 of 16** Max update types are handled: `message_created`, `message_callback`, `user_added`, `user_removed`. Rest logged as "Unsupported Update."
- **Max docs source**: `https://dev.max.ru/docs-api` — fetched 2026-06-29. Webhook events stored in project memory (id `52755987-4a03-4464-abf7-717df512f59e`).
  - Subscription: `POST /subscriptions` with `url`, `update_types`, `secret`. Secret sent back as `X-Max-Bot-Api-Secret` header.
  - TLS validation required for webhook endpoint (CN/SAN match, full chain, CA-trusted or Минцифры cert).
  - Rate limit: 30 rps on platform-api2.
  - `GET /chats` deprecated as of June 2026 — use `POST /subscriptions` instead.
  - Минцифры certificate: two PEM files from `https://www.gosuslugi.ru/crt` — `russian_trusted_root_ca_pem.crt` and `russian_trusted_sub_ca_pem.crt`.
  - No official Python SDK — `lib/max_bot/` is hand-rolled and must be updated.

## Implementation Summary (2026-06-29)

Plan: `docs/archive/plans/max-api-migration.md`. The endpoint migration + certificate trust has been fully implemented, reviewed, and tested (2710 tests pass).

### Files changed:
- `lib/max_bot/constants.py` — `API_BASE_URL` → `platform-api2.max.ru`, `DEFAULT_RATE_LIMIT` 100→30
- `lib/max_bot/utils.py` — `buildMaxSslContext(caBundlePath)` loads PEM certs from directory into `ssl.SSLContext` (additive to system CAs), with try/except for GOST certs on non-GOST platforms
- `lib/max_bot/client.py` — optional `caBundlePath` param on `MaxBotClient.__init__` (builds SSL context internally via `buildMaxSslContext()`), conditional `verify=` in `_getHttpClient`, SSL context threaded into SOCKS5 transport via `ProxyConfig.toKwargs(verify=...)`
- `internal/bot/max/application.py` — SSL context built from `[bot].max-ca-bundle` config and passed to `MaxBotClient` (raw config value, no intermediate resolution function)
- `configs/00-defaults/00-config.toml` — `max-ca-bundle = "../certs/max"` under `[bot]` (relative to `application.root-dir` which is `"storage"` → resolves to `<repo-root>/certs/max/`)
- `certs/max/` — 5 Минцифры CA PEM files (3 RSA + 2 GOST)
- `tests/lib/max_bot/test_client.py` — 14 tests (constants, SSL context loading, GOST skip, SOCKS5+SSL, caBundlePath pass-through)
- `tests/bot/max/test_application.py` — 3 tests (path resolution relative to cwd, absolute pass-through, empty returns empty) — **DELETED** 2026-07-01: `_resolveCaBundlePath` was removed; tests were stale
- `docs/llm/configuration.md` — max-ca-bundle in bot config table
- `docs/llm/libraries.md` — Max bot section updated with new API, SSL, deprecation
- `docs/developer-guide.md` — endpoint, rate limit, retries updated

### Bugs found and fixed:
1. **GOST cert crash**: `russian_trusted_root_ca_gost_2025.pem` and `russian_trusted_sub_ca_gost_2025.pem` crash `ssl.SSLError` on macOS (no GOST engine). Fixed with try/except per-cert load.
2. **Relative path + cwd change** (final fix): `ConfigManager.__init__` does `os.chdir(rootDir)` to `storage/`. To keep path behavior consistent across the whole project, `max-ca-bundle` is now `"../certs/max"` — relative to `application.root-dir`, resolves to `<repo-root>/certs/max/`. The raw config value is passed directly to `MaxBotClient`; path resolution happens inside `buildMaxSslContext()` in `lib/max_bot/utils.py`. The initially-attempted `_STARTUP_CWD` special-case was reverted as confusing (it made `max-ca-bundle` behave differently from all other paths).
3. **SOCKS5 + verify drop**: httpx ignores top-level `verify=` when a custom `transport=` is supplied. Fixed by threading the SSL context into the transport via `ProxyConfig.toKwargs(verify=self._sslContext)` (which calls `AsyncProxyTransport.from_url(proxyUrl, verify=sslContext)` for SOCKS5) and guarding the client-level `verify=` with `"transport" not in proxyKwargs`.
