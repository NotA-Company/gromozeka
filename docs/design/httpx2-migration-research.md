# Research: httpx → httpx2 migration feasibility

**Date**: 2026-08-13 (sources verified this date)
**Status**: Research complete. Verdict below. No code changed.
**Outcome**: **ADOPTED.** The verdict ("worth migrating incrementally") was
accepted and the migration **landed** — see the companion design doc
[`httpx2-migration-v1.md`](./httpx2-migration-v1.md) (now marked IMPLEMENTED).
`httpx[http2]==0.28.1` + `httpx-socks[asyncio]==0.11.0` were removed;
`httpx2[http2,socks]==2.10.0` is the sole HTTP library. PTB strategy **b2**
(`httpx2.alias_httpx()` at the top of `main.py`) was chosen. `make test` 3942
passed / 11 skipped / 0 failed; `make lint` 0 pyright errors. The HTTP/2-over-SOCKS
probe was resolved (closed-by-analysis on 2026-08-13 — HTTP/2 works over SOCKS5).
Remaining operator smokes (Минцифры-SSL-through-SOCKS, live Telegram round-trip)
remain pending — see design doc §8.
**Companion doc**: [`httpx2-migration-v1.md`](./httpx2-migration-v1.md) — design + phased implementation plan
**Scope**: Evaluate whether Gromozeka should migrate its HTTP layer from `httpx` to `httpx2`, and on what timeline.

> This document records already-completed research. Findings are preserved in
> full; the verdict is binding for the companion design doc. All external facts
> were verified on **2026-08-13**. Anything still unverified is marked as such.

---

## 1. Bottom line

**httpx2 is a real, legitimate, actively-maintained package.** It is a **fork of
`httpx 0.28.1`** published under the **Pydantic organization** (Pydantic Services
Inc.), maintained by Marcelo Trybiński (Kludex), released via OIDC Trusted
Publishing with Sigstore attestations from `github.com/pydantic/httpx2`. First
release `2.0.0` shipped **2026-05-12**; latest **`2.10.0` (2026-08-09)** — a rapid
~monthly cadence.

It is a **near-drop-in rename** (`import httpx` → `import httpx2`), not a rewrite.
Its stated motivation: upstream `encode/httpx` has seen limited activity. Notable
adopters already migrating: **Starlette** (encode's own sister project) and the
**MCP Python SDK**.

**Verdict (summary): worth migrating, but incrementally and not urgently.**
Full verdict in §10. Gromozeka already pins `httpx[http2]==0.28.1` (the current
httpx stable), so nothing is broken today; this is opportunistic modernization,
not a rescue. The companion design doc implements the recommended phased path.

---

## 2. Does httpx2 exist as a real, distinct project? — YES

- PyPI `httpx2` exists, latest `2.10.0` (2026-08-09). Owner on PyPI = the
  `pydantic` org; maintainer **Kludex**. It is **NOT** official `encode` — it is a
  third-party fork, but from a highly credible organization, not an anonymous or
  typosquat actor.
- **Supply-chain posture: strong.** OIDC Trusted Publishing from
  `github.com/pydantic/httpx2`, with Sigstore transparency-log entries. License
  BSD-3-Clause (same as httpx).
  - Note: the PyPI "Author" field reads "Tom Christie". This is **inherited fork
    metadata**, not evidence that Tom Christie joined the project.
- **Release history (rapid):** `0.0.0` (2026-05-11) → `2.0.0b1` (2026-05-11) →
  `2.0.0` (2026-05-12) → `2.1` (2026-05-15) → `2.2` (2026-05-16) → `2.3`
  (2026-06-01) → `2.4` (2026-06-11) → `2.5` (2026-06-25) → `2.6`/`2.7`
  (2026-07-14) → `2.8`/`2.9`/`2.9.1` (2026-07-23/24) → `2.10.0` (2026-08-09).
- GitHub `pydantic/httpx2`: ~903 stars, 50 forks, 2,246 commits, active CI.
- **There is NO official httpx v2 from encode.** encode is slowly working on a
  `1.0`, but PyPI shows only pre-releases: `1.0.dev1` (2025-07-02),
  `1.0.dev2` (2025-08-04), `1.0.dev3` (2025-09-15) — then ~11 months of silence.
  The "Roadmap for 1.0 release?" discussion
  (`github.com/encode/httpx/discussions/2279`) has been **Unanswered since
  2022-06**.
- **Ruled out:** it is NOT a typo for httpcore / aiohttp / niquests; NOT the httpx
  0.x → 1.0 transition (that is a separate, stalled encode effort); NOT a Chinese
  mirror / typosquat. It IS literally a fork under a new namespace.

---

## 3. Current state of httpx itself

- **Latest stable: `0.28.1`**, released **2024-12-06** (~20 months ago as of the
  verification date). The 0.28.1 fix is a single SSL bugfix.
- **Maintenance cadence: slow and slowing.** Last three stable releases:
  `0.27.0` (2024-02) → `0.27.2` (2024-08) → `0.28.0`/`0.28.1` (2024-11/12). Then
  no stable for ~20 months; only the three `1.0.dev*` pre-releases (2025-07 →
  2025-09), then silence.
- Still classified `4 - Beta` on PyPI (httpx2 is `5 - Production/Stable`). httpx
  never reached 1.0.
- The 0.x → 1.0 breaking transition has **not** happened in a stable release
  (dev pre-releases only). `0.28.0` (2024-11) shipped deprecations presaging 1.0:
  removed `proxies=` (use `proxy=`/`mounts=`), removed `app=` (use
  `WSGITransport()`/`ASGITransport()`), deprecated `verify=<path>` and `cert=`,
  compact JSON bodies.
- **Important for this repo:** Gromozeka pins `httpx[http2]==0.28.1` — the
  *current* httpx stable. It is **not** on an ancient httpx. The "hasn't been
  updated in several years" observation applies to the dependency's release
  cadence, not to our pin. The decision is purely **stay on httpx 0.28.1 vs swap
  to httpx2 2.x**.

---

## 4. httpx2 vs httpx — what changes

Sources: `httpx2.pydantic.dev/migration/`, CHANGELOG `2.0.0b1`; httpx2 `2.0.0`
forked from httpx `0.28.1` commit `b5addb6` — same public API surface.

### 4.1 Breaking at the 2.0.0 fork point

- Package / import rename `httpx` → `httpx2`; CLI is `httpx2`.
- Default User-Agent `python-httpx2/<ver>`.
- Loggers `httpx2` / `httpcore2.*`.
- Transitive dep renamed `httpcore` → `httpcore2` (vendored as a uv workspace
  member, pinned exactly) — direct `httpcore` imports must switch to `httpcore2`.
- **No other public API changed at 2.0.0.**

### 4.2 Behavior differences accumulated in 2.x

| Change | Since | Note |
|---|---|---|
| SSL uses `truststore` (OS trust store) instead of bundled `certifi` certs | 2.3.0 | `SSL_CERT_FILE` / `SSL_CERT_DIR` still honored; `verify=` still works |
| Python ≥ 3.10 required (dropped 3.9) | 2.1.0 | httpx supports ≥ 3.8; Gromozeka is on 3.12, so non-issue |
| `HTTPXDeprecationWarning` visible by default | 2.4.0 | — |

### 4.3 New features gained in 2.x

- Built-in **Server-Sent Events** (`client.sse()`, 2.5.0; replaces `httpx-sse`).
- Built-in **WebSockets** (`httpx2[ws]`, 2.6.0; replaces `httpx-ws`).
- `QUERY` method (2.6.0).
- RFC 9110 status constants (2.10.0).
- Pyodide / Emscripten transport (2.10.0).
- Python 3.14 / 3.15 support.
- First-class Pydantic Logfire instrumentation.

### 4.4 Drop-in or rewrite? — NEAR DROP-IN

For an application depending on httpx directly: swap the dep,
`import httpx2 as httpx`, done. Both packages **can coexist** in one environment
(distinct import names).

**CAVEAT — the object boundary.** Objects do NOT cross the boundary:
`httpx2.Client` is not `httpx.Client`, so `isinstance(...)` and `except` clauses
across mixed dependencies fail. Escape hatch `httpx2.alias_httpx()` (2.9.0) makes
`import httpx` resolve to `httpx2` process-wide (apps only; must be called first).
The migration guide states: *"After this call, `import httpx` resolves to
`httpx2` and `import httpcore` resolves to `httpcore2`, process-wide … isinstance()
checks pass and except clauses catch across the boundary."*

### 4.5 Adoption / credibility

- **Starlette** (encode's own sister project) migrated its `TestClient` to prefer
  httpx2 with an httpx fallback (`encode/starlette#3291`).
- **MCP Python SDK** replaced httpx + httpx-sse with httpx2 for its v2
  (`modelcontextprotocol/python-sdk#2972`).
- The maintainer organization maintains pydantic itself.
- **Caveat:** 903 stars vs httpx's ~15.4k — real but early.

### 4.6 Security / supply-chain

Low concern: OIDC Trusted Publishing from the verified `pydantic/httpx2` repo
with Sigstore attestations; the maintainer is a known public figure. The one real
risk is **ecosystem bifurcation**: two incompatible object hierarchies across the
dependency tree until convergence.

---

## 5. The crux for this codebase — SOCKS / proxy

- **httpx2 supports SOCKS NATIVELY** via the `httpx2[socks]` extra (`socksio`):

  ```python
  httpx2.AsyncClient(proxy="socks5://host:port", verify=sslContext)
  ```

  This is **inherited** from httpx / httpcore (httpx 0.28.1 also had
  `httpx[socks]` + `proxy='socks5://'`). So the `httpx-socks` dependency in
  Gromozeka was a **transport-object choice** (needed to thread `verify=` into
  PTB's `HTTPXRequest(transport=...)`), not because httpx lacked native SOCKS.

- **No dedicated httpx2-socks fork exists, and none is needed.** `httpx-socks`
  (romis2012) `v0.11.0` is still maintained but imports `httpx` and returns httpx
  transport types — it builds transports for `httpx.Client`, **not**
  `httpx2.Client` (the object-boundary problem). Known issue
  `romis2012/httpx-socks#2` ("HTTP/2 not working" with
  `AsyncProxyTransport.from_url` + `http2=True`) confirms `httpx-socks`'
   `from_url()` accepts `http2=True` but HTTP/2-over-SOCKS had an httpx-socks
   config/propagation bug (matches Gromozeka's own gotcha that forces `http2=False` when SOCKS is
   active — see §8). `httpcore2` actively maintains the SOCKS+SSL path (changelog:
  *"Fix trace extension when used with socks proxy (#849/#880)"*, *"Fix SSL
  context for connections using the 'wss' scheme (#869)"* in the 1.0.x line).

- **Gromozeka-owned httpx clients migrate cleanly** (Max bot, yandex_search, the
  `lib/proxy` layer):

  ```text
  transport=AsyncProxyTransport.from_url(url, verify=sslContext)
    →  proxy="socks5://host:port", verify=sslContext
  ```

  The Минцифры CA `sslContext` threads to the end-to-end TLS handshake (SOCKS
  only tunnels TCP; TLS is client ↔ target).

  - **One thing to validate by test:** that `verify=` correctly reaches target
    TLS when `proxy="socks5://..."` is set. The httpcore2 `#869`/`#880` fixes
    suggest yes; **verify empirically against a real Минцифры-signed endpoint.**

- The `lib/proxy/__init__.py` `toKwargs()` becomes
  `ProxyKwargs(proxy="socks5://...")` instead of `transport=...`.

---

## 6. The single real cost = python-telegram-bot (PTB)

PTB 22.8 owns its own `httpx` clients. In
`internal/bot/telegram/application.py`, the SOCKS5 branch passes
`HTTPXRequest(httpx_kwargs=proxyConfig.toKwargs())`; PTB internally constructs
`httpx.AsyncClient`. Three sub-options:

- **(b1) Keep `httpx` + `httpx-socks` ONLY for the Telegram subsystem.**
  Lowest risk. Cost: httpx and httpx-socks stay pinned; you live with the object
  boundary (PTB clients are `httpx.Client`, your code is `httpx2.Client` — do not
  mix objects across).
- **(b2) `httpx2.alias_httpx()` escape hatch.** Call it at the very top of
  `main.py`, before PTB imports (see migration guide quote in §4.4). Risk:
  httpx2 switches SSL to `truststore` (OS trust store) away from `certifi` — must
  confirm PTB's certificate handling still works; a global rewrite needs a
  dedicated test pass against the Telegram API.
- **(b3) Wait for PTB to migrate.** PTB has not announced an httpx2 move; do not
  block on it.

`sqlink` (git dependency) also uses httpx internally — same boundary logic; it has
its own `proxy=` parameter, so it is unaffected.

---

## 7. Dependency-pin reconciliation

Verified by reading the repo's requirements files.

**`requirements.direct.txt`** (direct deps only):

- Line 9: `httpx[http2]==0.28.1`
- Line 10: `httpx-socks[asyncio]==0.11.0`

That is the **complete** httpx-ecosystem set in the direct file. **No** `httpx-sse`.
**No** `httpcore`. **No** `socksio` / `python-socks` as direct deps.

**`requirements.txt`** (frozen / lockfile):

- `httpcore==1.0.9`
- `httpx==0.28.1`
- `httpx-socks==0.11.0`
- `httpx-sse==0.4.3`
- `python-socks==2.8.2`
- (plus `h11` / `h2` / `hpack` / `hyperframe` for the HTTP/2 stack)

**`httpx-sse==0.4.3`** is present in the frozen file but is **transitive** (pulled
by `yandex-ai-studio-sdk==0.22.0`), **not a direct dep**, and a codebase-wide
grep for `httpx_sse` returns **zero** `*.py` matches. It does **not** affect the
migration. (If Gromozeka ever adopts httpx2's built-in SSE `client.sse()`,
`httpx-sse` remains compatible; `yandex-ai-studio-sdk` will keep dragging it
transitively until that SDK migrates.)

---

## 8. Codebase coupling

From a thorough explore pass.

- **Async-only** (no sync `httpx.Client`). ~11 production import sites + ~7 test
  files.
- **Production httpx import sites:** `lib/proxy/__init__.py`,
  `lib/max_bot/client.py`, `lib/openweathermap/client.py`,
  `lib/yandex_search/client.py`, `lib/geocode_maps/client.py`,
  `lib/stt/providers/yandex_speechkit.py`, `lib/ai/providers/openrouter_provider.py`,
  `lib/ai/providers/basic_openai_provider.py`,
  `lib/aurumentation/{transports,recorder,provider,replayer}.py`,
  `internal/bot/common/handlers/yandex_search.py`,
  `internal/services/proxy/lifecycle.py`.
- **Features used:**
  - `httpx.AsyncClient` (async only); get/post/put/patch/delete/request.
  - **One** streaming site: `lib/max_bot/client.py`
    `client.stream("POST", ...)`.
  - Proxy via `proxy=` (HTTP) and
    `transport=AsyncProxyTransport.from_url(url, verify=sslContext)` (SOCKS5,
    conditional import with `_HTTPX_SOCKS_AVAILABLE` flag).
  - Custom transports — `RecordingTransport` / `ReplayTransport` subclass
    `httpx.AsyncHTTPTransport` and override `handle_async_request()` (in
    `lib/aurumentation/transports.py`).
  - `httpx.Timeout` extensively.
  - **No** `httpx.Limits`, **no** auth classes (auth via headers), **no** cookies,
    **no** event hooks.
  - `httpx.URL` used once.
  - Exceptions caught: `httpx.HTTPError`, `httpx.HTTPStatusError`,
    `httpx.ReadTimeout`, `httpx.RequestError`, `httpx.TimeoutException`.
  - Response handling: `.json()` / `.text` / `.content` / `.status_code` /
    `.headers` / `.raise_for_status()`.
- **Test coupling:**
  - `httpx.MockTransport(handler)` (primary pattern, e.g.
    `tests/lib/stt/providers/test_yandex_speechkit.py`).
  - `AsyncMock(spec=...)` / patching `httpx.AsyncClient` as context manager
    (e.g. `tests/lib/ai/providers/test_basic_openai_provider.py`).
  - Direct `ReplayTransport` testing
    (`tests/lib/aurumentation/test_replay_transport.py`).
  - Proxy testing patching `lib.proxy.AsyncProxyTransport`.
- **HTTP/2 conditional-disable gotcha:** the web-fetch handler keys HTTP/2 off the
  presence of a transport object:

  ```text
  useHttp2 = "transport" not in self._proxyConfig.toKwargs()
  # internal/bot/common/handlers/yandex_search.py:567
  ```

   (SOCKS transport incompatible with HTTP/2 — refuted post-migration; see the outcome note above and ADR-021.)
- **Coupling rating: MEDIUM-HIGH — but** it is coupling to httpx internals that
  are API-identical in httpx2 (it is a fork from 0.28.1). The custom transport
  subclasses, the exception hierarchy, the SSL threading, and `MockTransport` all
  port by import-rename. The genuinely load-bearing coupling is the **SOCKS proxy
  system + the Минцифры SSL contexts** — that is what the empirical verification
  in §5 protects.

---

## 9. (reserved — findings continue in §10)

## 10. Verdict

**Worth migrating, but INCREMENTALLY and NOT URGENTLY.** The motivation is
maintenance / security velocity — httpx2 is the same code, so there is **no
performance gain**. Gromozeka is already on the latest httpx, so nothing is broken
today; treat this as **opportunistic modernization, not a rescue.**

- **No reason to switch to a different library entirely** (niquests / aiohttp) —
  httpx / httpx2 already covers async + HTTP/2 + SOCKS + SSE for this project; a
  full library swap would be a rewrite for no gain.

**Pros of migrating:**

- Active maintenance / security velocity (monthly vs httpx's ~2-year stable gap).
- Drops `httpx-socks` for owned code (native `httpx2[socks]`).
- Ecosystem momentum (Starlette / MCP).
- Built-in SSE / WS.
- OS-trust-store SSL (`truststore`).

**Cons / costs:**

- Mechanical churn (import rename across ~18 files, swap two pins).
- PTB is the real friction: carry two HTTP libraries with object-boundary
  discipline, **OR** an `alias_httpx()` global-rewrite spike needing a
  Telegram + SSL validation pass.
- Early-adoption risk (903 vs 15.4k stars; ecosystem bifurcation until
  convergence).
- No urgent trigger.

**Recommended incremental path:**

- **Phase 1** — migrate Gromozeka-owned clients (Max, yandex_search, the
  `lib/proxy` layer) to `httpx2[socks]` native SOCKS, drop `httpx-socks` there,
  empirically verify the Минцифры CA through the SOCKS tunnel.
- **Phase 2** — decide PTB's fate (keep `httpx-socks` for it, or do an
  `alias_httpx()` spike).
- Deferring until a natural trigger (a security advisory landing faster in httpx2,
  a PTB major bump, wanting built-in SSE/WS) is also defensible.

**Waiting for official httpx 1.0 is a gamble** — it has been "coming" for 4+ years
with no timeline.

---

## 11. References

All accessed **2026-08-13**.

- https://pypi.org/project/httpx2/
- https://github.com/pydantic/httpx2
- https://httpx2.pydantic.dev/migration/
- https://github.com/pydantic/httpx2/blob/main/src/httpx2/CHANGELOG.md
- https://httpx2.pydantic.dev/advanced/proxies/
- https://httpx2.pydantic.dev/third_party_packages/
- https://pypi.org/project/httpx/
- https://github.com/encode/httpx/releases
- https://github.com/encode/httpx/discussions/2279
- https://github.com/encode/starlette/pull/3291
- https://github.com/modelcontextprotocol/python-sdk/pull/2972
- https://github.com/romis2012/httpx-socks/issues/2