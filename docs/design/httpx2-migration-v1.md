# Design: httpx → httpx2 migration (v1)

**Date**: 2026-08-13
**Status**: PROPOSED (unimplemented). Optional, opportunistic modernization.
**Owner**: TBD
**Companion doc**: [`httpx2-migration-research.md`](./httpx2-migration-research.md) — research, comparison, and verdict (read first for the *why*).
**Scope**: Migrate Gromozeka's HTTP layer from `httpx` to `httpx2` incrementally, preserving all current behavior. No full library swap.

> This is a **behavior-preserving** migration. httpx2 is a fork of httpx `0.28.1`
> with an identical public API surface (see research doc §4); the existing test
> suite is the primary safety net. Every phase is independently revertible via
> git. Nothing here is shipped yet — this document describes the intended end
> state. Code snippets are illustrative of the intended change and follow the
> repo's camelCase convention; they are not committed source.

---

## 1. Context and goal

Gromozeka pins `httpx[http2]==0.28.1` (the current httpx stable) plus
`httpx-socks[asyncio]==0.11.0` for SOCKS5 support threaded through PTB. Upstream
httpx has been on a ~20-month stable-release gap with a stalled 1.0 effort, while
`httpx2` (a Pydantic-org fork of the same 0.28.1 codebase) ships monthly and is
gaining ecosystem momentum (Starlette, MCP Python SDK). The full comparison,
supply-chain assessment, and verdict live in the
[research doc](./httpx2-migration-research.md).

**Verdict in one paragraph:** worth migrating, but incrementally and not urgently.
httpx2 is the same code (no performance gain); the motivation is maintenance and
security velocity. The decision is "stay on httpx 0.28.1 vs swap to httpx2 2.x,"
not a rescue. The single real cost is `python-telegram-bot`, which owns its own
httpx clients; everything else Gromozeka owns migrates as a near-drop-in rename
plus a proxy-layer simplification.

### 1.1 Goals

- **G1** — Migrate Gromozeka-owned HTTP clients from `httpx` to `httpx2`, preserving
  all current behavior (async-only, HTTP/2, SOCKS5 proxy, Минцифры CA trust).
- **G2** — Replace the `httpx-socks` transport-object indirection in owned code
  with native `httpx2[socks]` (`proxy="socks5://..."`), simplifying the
  `lib/proxy` layer.
- **G3** — Do it in independently-shippable phases so the PTB subsystem can be
  decided separately and each phase can roll back on its own.

### 1.2 Non-goals

- **NG1** — No full library swap (no niquests, no aiohttp). httpx/httpx2 already
  covers async + HTTP/2 + SOCKS + SSE for this project.
- **NG2** — No end-user-visible behavior change. This is a wiring/dependency
  migration, not a feature.
- **NG3** — No adoption of httpx2's *new* features (built-in SSE `client.sse()`,
  WebSockets, `QUERY` method) as part of this migration. Those are separate
  features evaluated on their own merit; this design only preserves what exists.
- **NG4** — No change to the SQLite/SQL layer. The SQL-portability rules in
  `AGENTS.md` do not apply to this migration.

---

## 2. Verified grounding (current state)

The following are facts verified against source on 2026-08-13, not assumptions.
Line numbers are current.

### 2.1 Dependency pins

[`requirements.direct.txt`](../../requirements.direct.txt):

```text
9: httpx[http2]==0.28.1
10: httpx-socks[asyncio]==0.11.0
```

That is the complete httpx-ecosystem set in the direct file. [`requirements.txt`](../../requirements.txt)
(frozen) additionally carries the transitive `httpcore==1.0.9`,
`httpx-sse==0.4.3` (pulled by `yandex-ai-studio-sdk`, zero `*.py` imports),
`python-socks==2.8.2`, and the HTTP/2 stack (`h11`/`h2`/`hpack`/`hyperframe`).

### 2.2 The proxy layer — `lib/proxy/__init__.py`

Conditional import and availability flag ([`lib/proxy/__init__.py`](../../lib/proxy/__init__.py):17-22):

```python
try:
    from httpx_socks import AsyncProxyTransport

    _HTTPX_SOCKS_AVAILABLE = True
except ImportError:
    _HTTPX_SOCKS_AVAILABLE = False
```

The kwargs shape ([`lib/proxy/__init__.py`](../../lib/proxy/__init__.py):105-118):

```python
class ProxyKwargs(TypedDict, total=False):
    proxy: str
    """HTTP proxy URL string ... Passed directly to httpx.AsyncClient(proxy=...)."""
    transport: "AsyncProxyTransport"
    """SOCKS5 transport instance from httpx_socks.AsyncProxyTransport.
    Passed to httpx.AsyncClient(transport=...)."""
```

`toKwargs()` SOCKS5 branch ([`lib/proxy/__init__.py`](../../lib/proxy/__init__.py):476-484):

```python
if config.type == ProxyType.SOCKS5:
    if not _HTTPX_SOCKS_AVAILABLE:
        raise ImportError(
            "SOCKS5 proxy requires httpx-socks[asyncio] package. ..."
        )
    if verify is not None:
        return ProxyKwargs(transport=AsyncProxyTransport.from_url(proxyUrl, verify=verify))
    return ProxyKwargs(transport=AsyncProxyTransport.from_url(proxyUrl))
```

Note: `lib/proxy/__init__.py` does **not** `import httpx` directly — it only imports
`httpx_socks`. The HTTP-proxy branch already returns `ProxyKwargs(proxy=proxyUrl)`.

### 2.3 The two callers that branch on `"transport" in proxyKwargs`

**Max client** ([`lib/max_bot/client.py`](../../lib/max_bot/client.py):226-242) threads `verify=`
onto the client only when there is no custom transport:

```python
proxyKwargs = self._proxyConfig.toKwargs(verify=self._sslContext)
clientKwargs: Dict[str, Any] = {
    **proxyKwargs,
    "base_url": self.baseUrl,
    "timeout": httpx.Timeout(self.timeout),
    "headers": {"User-Agent": f"Gromozeka/{VERSION}"},
}
if "transport" not in proxyKwargs and self._sslContext is not None:
    clientKwargs["verify"] = self._sslContext
httpClient = httpx.AsyncClient(**clientKwargs)
```

**Web-fetch handler** ([`internal/bot/common/handlers/yandex_search.py`](../../internal/bot/common/handlers/yandex_search.py):566-573)
disables HTTP/2 when a SOCKS transport is present:

```python
proxyKwargs = self._proxyConfig.toKwargs()
useHttp2 = "transport" not in proxyKwargs
if not useHttp2:
    logger.warning("HTTP/2 disabled for web-fetch: SOCKS5 transport does not support HTTP/2")

async with httpx.AsyncClient(
    **proxyKwargs,
    http2=useHttp2,
    ...
```

### 2.4 The PTB wiring — `internal/bot/telegram/application.py`

The SOCKS5 branch builds two `HTTPXRequest` instances from `toKwargs()`
([`internal/bot/telegram/application.py`](../../internal/bot/telegram/application.py):370-378):

```python
case ProxyType.SOCKS5:
    mainRequest = HTTPXRequest(httpx_kwargs=proxyConfig.toKwargs())  # pyright: ignore[reportArgumentType]
    getUpdatesRequest = HTTPXRequest(
        httpx_kwargs=proxyConfig.toKwargs()  # pyright: ignore[reportArgumentType]
    )
    appBuilder = appBuilder.request(mainRequest).get_updates_request(getUpdatesRequest)
```

PTB 22.8 constructs `httpx.AsyncClient` internally from those kwargs. The Telegram
subsystem is the one place that is **not** Gromozeka-owned HTTP code.

### 2.5 Custom transports — `lib/aurumentation/transports.py`

Two subclasses of `httpx.AsyncHTTPTransport` overriding `handle_async_request`
([`lib/aurumentation/transports.py`](../../lib/aurumentation/transports.py):19, 43, 94, 210):

```python
import httpx

class RecordingTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response: ...

class ReplayTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response: ...
```

`ReplayTransport` constructs responses directly
([`lib/aurumentation/transports.py`](../../lib/aurumentation/transports.py):298):

```python
response = httpx.Response(
    status_code=call["response"]["status_code"],
    headers=call["response"]["headers"],
    content=call["response"]["content"].encode() if call["response"]["content"] else b"",
)
```

These modules do **not** import `httpcore` directly (verified — the only
`httpcore` reference in the codebase is a logging-level setting in
[`lib/logging_utils.py`](../../lib/logging_utils.py):118). So there is **no**
`httpcore` → `httpcore2` source change required beyond the logger name.

### 2.6 Import surface

A grep for `^import httpx$` finds **13 production sites** and **6 test files**
that import httpx directly (the research doc's "~11 production + ~7 test" figure
is the same set, counted before `internal/services/proxy/lifecycle.py` was added).
`httpx.MockTransport` is the primary test-transport pattern
([`tests/lib/stt/providers/test_yandex_speechkit.py`](../../tests/lib/stt/providers/test_yandex_speechkit.py):157).
The single streaming call site is
[`lib/max_bot/client.py`](../../lib/max_bot/client.py):1628
(`client.stream("POST", uploadUrl, files=files)`).

---

## 3. Architecture decisions

### D1 — Migration strategy: incremental phased, NOT big-bang

Adopt a four-phase plan (§7). Phase 1 migrates owned clients; Phase 2 decides the
PTB subsystem independently; Phase 3 is cleanup. Both httpx and httpx2 coexist in
the tree until Phase 3 (which only runs if Phase 2 picks the global-rewrite
option). Rationale: the research verdict (§10 of the research doc) explicitly
calls for incremental, non-urgent migration; a big-bang would couple the
low-risk owned-client rename to the high-risk PTB decision.

### D2 — Proxy layer: native `proxy=` replaces the transport object

Replace the SOCKS5 transport-object indirection with native httpx2 SOCKS.

**`lib/proxy/__init__.py` changes:**

- Remove the `from httpx_socks import AsyncProxyTransport` conditional import and
  the `_HTTPX_SOCKS_AVAILABLE` flag. Native `httpx2[socks]` pulls `socksio`; if
  the extra is absent, httpx2 raises a clear error at client-construction time
  when `proxy="socks5://..."` is used. No application-level availability guard is
  needed.
- Drop the `transport` key from `ProxyKwargs`. The dict collapses to a single
  `proxy: str` key used for **both** HTTP and SOCKS5:

  ```python
  class ProxyKwargs(TypedDict, total=False):
      proxy: str
      """Proxy URL string (http://... or socks5://...). Passed to
      httpx2.AsyncClient(proxy=...)."""
  ```

- `toKwargs()` no longer takes a `verify` parameter. Both proxy types return
  `ProxyKwargs(proxy=proxyUrl)`; the caller applies `verify=` at the
  `httpx2.AsyncClient` level uniformly. The SOCKS5 branch becomes:

  ```python
  if config.type == ProxyType.SOCKS5:
      return ProxyKwargs(proxy=proxyUrl)
  ```

- The module still does **not** need to `import httpx2` — it only produces a
  plain kwargs dict.

**Caller simplification (load-bearing):** the two `"transport" not in proxyKwargs`
special-cases disappear because there is never a `transport` key. `verify=` is
always applied at the client level. In `lib/max_bot/client.py` `_getHttpClient`,
the conditional collapses to:

```python
proxyKwargs = self._proxyConfig.toKwargs()
clientKwargs: Dict[str, Any] = {
    **proxyKwargs,
    "base_url": self.baseUrl,
    "timeout": httpx2.Timeout(self.timeout),
    "headers": {"User-Agent": f"Gromozeka/{VERSION}"},
}
if self._sslContext is not None:
    clientKwargs["verify"] = self._sslContext
httpClient = httpx2.AsyncClient(**clientKwargs)
```

**Empirical verification (gate, §8):** confirm `verify=<Минцифры sslContext>`
reaches the target TLS handshake when `proxy="socks5://..."` is set. SOCKS only
tunnels TCP; TLS is client ↔ target. httpcore2 changelog fixes
("Fix SSL context for connections using the 'wss' scheme (#869)", SOCKS+trace
fixes #849/#880) suggest this works, but it must be smoke-tested against a real
Минцифры-signed endpoint before Phase 1 ships.

### D3 — HTTP/2 conditional-disable: key off proxyType, not transport presence

The current heuristic (`useHttp2 = "transport" not in proxyKwargs`) detects SOCKS
*indirectly*, via the transport object. After D2 there is no transport object, so
that check would always return `True` — silently re-enabling HTTP/2 over SOCKS,
which is the historically-flaky combination the guard exists to avoid (research
doc §5; `romis2012/httpx-socks#2`).

**New rule — detect SOCKS directly:**

```python
resolvedType = self._proxyConfig.getCombined().type
useHttp2 = resolvedType != ProxyType.SOCKS5
```

This is semantically correct (the disable condition *is* "SOCKS5 active") and no
longer depends on a transport object's incidental presence. It also survives a
future world where HTTP/2-over-SOCKS is fixed in httpcore2 — at that point the
guard can be removed in a one-line change keyed on the same `proxyType` check.

**Open question (§9):** whether HTTP/2-over-SOCKS now works in httpcore2. If a
smoke test shows it does, the guard can be dropped; until then, keep it.

### D4 — PTB strategy: b1 recommended, b2 alternative — DECIDE IN PHASE 2

This is the one decision explicitly left open. Two viable strategies for the
Telegram subsystem:

- **(b1) Keep `httpx` + `httpx-socks` for Telegram only (RECOMMENDED default).**
  PTB 22.8 keeps constructing its own `httpx.AsyncClient` via `HTTPXRequest`; the
  SOCKS5 branch in `internal/bot/telegram/application.py` keeps passing
  `toKwargs()` (which, after D2, returns `{proxy: "socks5://..."}` — but note: PTB
  + `httpx-socks` still needs the *transport object*, so b1 means **retaining**
  `httpx-socks` and the transport path specifically for PTB, or accepting that PTB
  uses httpx's own `httpx[socks]` native support). Lowest risk: no global rewrite,
  no truststore/SSL spike. The cost is carrying two HTTP libraries and observing
  the object-boundary discipline (PTB clients are `httpx.Client`; do not pass them
  into code typed as `httpx2.Client`).

  > Refinement: because `toKwargs()` after D2 no longer produces a transport, b1
  > requires the Telegram wiring to build its own transport from `httpx-socks`
  > locally (PTB needs a transport for SOCKS over the *real* httpx), OR to rely on
  > `httpx[socks]` native `proxy=`. The Phase 2 spike resolves which. This is why
  > b1 is simple in principle but has a small PTB-local detail to nail down.

- **(b2) `httpx2.alias_httpx()` global rewrite.** Call `httpx2.alias_httpx()` at
  the very top of `main.py`, **before** the `from internal.bot.telegram.application
  import ...` line (line 18) which transitively imports httpx via PTB. After the
  call, `import httpx` resolves to `httpx2` process-wide, so PTB's internal
  `httpx.AsyncClient` becomes an `httpx2.AsyncClient` and the object boundary
  disappears. **Risks:** httpx2 switches SSL to `truststore` (OS trust store) away
  from `certifi`; PTB's certificate handling must be re-validated; the global
  rewrite needs a dedicated Telegram-API smoke pass.

**Recommended default: b1**, because it keeps the high-risk PTB+SSL change
isolated and makes Phase 2 independently shippable and revertible. The b2 spike is
worth running as a time-boxed experiment, but it should not gate Phase 1. **The
user has not decided; this is the Phase 2 decision point** (see §7 Phase 2 and §9).

### D5 — Import convention: `import httpx2 as httpx`

Use the alias form everywhere in migrated files:

```python
import httpx2 as httpx
```

**Rationale:** the rename becomes a one-line-per-file change — every `httpx.AsyncClient`,
`httpx.Timeout`, `httpx.HTTPError`, `httpx.MockTransport` reference stays literally
identical, so the diff is minimal and reviewable. The alternative (`import httpx2`
+ rewrite every `httpx.X` → `httpx2.X`) is pure churn with no benefit.

**Constraint:** no single migrated file may also `import httpx` (the alias would
shadow). This holds for all Gromozeka-owned files — none of them import PTB
internals. PTB's own modules (under the installed `telegram/` package) are
untouched and keep using the real `httpx` (under b1) or the aliased one (under b2).

Add a one-line note to each migrated module's docstring: *"Uses `httpx2`
(aliased as `httpx`) — see `docs/design/httpx2-migration-v1.md`."*

### D6 — `lib/aurumentation/` transports port by subclass rename

`RecordingTransport` and `ReplayTransport` subclass `httpx.AsyncHTTPTransport`.
After D5 they subclass `httpx2.AsyncHTTPTransport` (via the alias). The
`handle_async_request(self, request: httpx.Request) -> httpx.Response` signature
is unchanged (httpx2 forked from 0.28.1; `httpx2.Request`/`httpx2.Response` are
API-identical). The `httpx.Response(...)` construction in `ReplayTransport`
ports directly. No `httpcore` imports exist in these modules (verified §2.5), so
there is **no** `httpcore` → `httpcore2` change here.

**Verification gate:** the aurumentation replay golden suites are byte-exact
comparisons ([`lib/aurumentation/transports.py`](../../lib/aurumentation/transports.py):182-186
docstring: *"Body comparison is byte-exact — if httpx's JSON serialization
changes, regenerate fixtures"*). Because httpx2 forked from 0.28.1, serialization
should be identical, but the golden suites are the regression net — they must
remain byte-identical. If a fixture drifts, that is a finding, not a silent
regenerate.

### D7 — Test strategy: rename `MockTransport`, keep golden suites, plan a PTB spike

- `httpx.MockTransport(handler)` → `httpx2.MockTransport(handler)` (same API; one
  import change per test file). The primary site is
  [`tests/lib/stt/providers/test_yandex_speechkit.py`](../../tests/lib/stt/providers/test_yandex_speechkit.py):157.
- The aurumentation replay golden suites (D6) must pass unchanged — they are the
  byte-exact regression net.
- Add a **proxy-layer unit test** for the D2 simplification: assert `toKwargs()`
  returns `{proxy: "socks5://..."}` for SOCKS5 and `{proxy: "http://..."}` for
  HTTP, with no `transport` key and no `verify` parameter.
- Add a **regression test** for D3: assert `useHttp2` is `False` when the resolved
  proxy type is `SOCKS5` and `True` otherwise (the test must fail against the old
  `"transport" not in proxyKwargs` heuristic once the transport key is gone — per
  the AGENTS.md "regression tests on every bug fix" rule, write it first).
- If Phase 2 picks **(b2)**, add a live Telegram-API smoke pass (manual gate, §8).

---

## 4. Dependency changes

All changes go in [`requirements.direct.txt`](../../requirements.direct.txt) under
the `# Runtime` section, with exact version pins. [`requirements.txt`](../../requirements.txt)
is regenerated via `freeze-requirements` — **never hand-edit it** (AGENTS.md).

### 4.1 Phase 0 (both libs coexist)

Add httpx2 alongside httpx (no removal yet):

```text
httpx2[http2,socks]==2.10.0   # NEW (line 9, alongside httpx[http2]==0.28.1)
```

httpx, httpx-socks, httpcore all stay.

### 4.2 Phase 1 (owned clients migrated; httpx-socks dropped for owned code)

`httpx-socks[asyncio]==0.11.0` stays pinned **only if** Phase 2 will keep it for
PTB (b1). The owned-client migration does not itself remove the pin — it removes
owned-code *imports* of `httpx_socks`. The pin's fate is decided in Phase 2.

| Package | Phase 0 | Phase 1 | Phase 2 (b1) | Phase 2 (b2) | Phase 3 |
|---|---|---|---|---|---|
| `httpx[http2]` | kept | kept | kept | kept | **removed** |
| `httpx2[http2,socks]` | **added** | kept | kept | kept | kept |
| `httpx-socks[asyncio]` | kept | kept | kept | **removed** | removed |
| `httpcore` (transitive) | kept | kept | kept | replaced by `httpcore2` | `httpcore2` |
| `httpx-sse` (transitive) | kept | kept | kept | kept | kept (dragged by yandex SDK) |

### 4.3 Note on `httpcore` → `httpcore2`

`httpcore2` is vendored as a uv workspace member, pinned exactly by httpx2. It
enters the tree as a transitive of `httpx2`. No Gromozeka source imports
`httpcore` (verified §2.5); the only `httpcore` reference is the logger-level
setting in [`lib/logging_utils.py`](../../lib/logging_utils.py):118, which must add
the `httpcore2` logger (and, under b2, replace `httpcore`). `httpx-sse` stays
transitive (pulled by `yandex-ai-studio-sdk`) and is unaffected.

---

## 5. Logging changes

Two logger-name touch points (no behavior change, only which loggers get silenced):

- [`main.py`](../../main.py):34 — `logging.getLogger("httpx").setLevel(...)`.
  Owned code now logs under the `httpx2` logger; add a parallel
  `logging.getLogger("httpx2").setLevel(logging.WARNING)`. Under b1, keep the
  `httpx` line too (PTB still uses it). Under b2, the `httpx` logger is the
  aliased `httpx2` logger, so the line is effectively redundant but harmless.
- [`lib/logging_utils.py`](../../lib/logging_utils.py):114/118 — add
  `httpx2` and `httpcore2` to the silenced loggers.

---

## 6. `alias_httpx()` placement (only if Phase 2 picks b2)

If (b2) is chosen, `httpx2.alias_httpx()` must run **before any module that imports
httpx is imported**. In [`main.py`](../../main.py), the first such import is line 18
(`from internal.bot.telegram.application import TelegramBotApplication`), which
transitively pulls httpx via PTB. The call goes at the very top of `main.py`,
immediately after the stdlib imports and before the `internal.*` imports:

```python
import httpx2

# Process-wide: make `import httpx` resolve to `httpx2` so PTB's internal
# httpx.AsyncClient becomes httpx2.AsyncClient (see docs/design/httpx2-migration-v1.md §6).
# MUST run before any import that transitively pulls httpx (e.g. PTB).
httpx2.alias_httpx()
```

This is the single most order-sensitive line in the whole migration; it gets its
own verification gate (live Telegram smoke, §8).

---

## 7. Phased implementation plan

Each phase: scope (exact files), steps, verification, and a Gate review. Hard
rules that apply to **every** phase (from AGENTS.md): **camelCase** for all
identifiers; invoke Python as `./venv/bin/python3` (never `python`/`python3`);
run `make format lint` **before AND after** edits; `make test` is mandatory after
any change; write a regression test first for any bug fix (D3's useHttp2 change
qualifies). SQL-portability rules do not apply (no SQL touched).

### Phase 0 — Preparation (both libs coexist, no behavior change)

**Scope:** `requirements.direct.txt`, regenerated `requirements.txt`.

**Steps:**

1. Add `httpx2[http2,socks]==2.10.0` to `requirements.direct.txt` under `# Runtime`.
2. Regenerate the lockfile via `freeze-requirements`.
3. Verify the import resolves (write a tiny throwaway script under `tests/` or
   reuse an existing one — do **not** use `python -c` per AGENTS.md).

**Verification:** `make format lint`; `make test` (full suite green — no source
changed, only a dep added); confirm `httpx2` and `httpx` both importable.

**Gate 0:** both libraries coexist; no production file imports httpx2 yet.

### Phase 1 — Migrate Gromozeka-owned clients + rework proxy layer

**Scope (exact files):**

- `lib/proxy/__init__.py` — D2 rework (remove `httpx_socks` import + flag, collapse
  `ProxyKwargs`, drop `verify` param from `toKwargs`).
- `lib/max_bot/client.py` — `import httpx2 as httpx`; simplify `_getHttpClient`
  (D2); streaming call site unchanged by name.
- `lib/openweathermap/client.py` — rename import.
- `lib/yandex_search/client.py` — rename import.
- `lib/geocode_maps/client.py` — rename import.
- `lib/stt/providers/yandex_speechkit.py` — rename import.
- `lib/ai/providers/openrouter_provider.py` — rename import.
- `lib/ai/providers/basic_openai_provider.py` — rename import.
- `lib/aurumentation/transports.py` — rename import (D6).
- `lib/aurumentation/recorder.py` — rename import.
- `lib/aurumentation/provider.py` — rename import.
- `lib/aurumentation/replayer.py` — rename import.
- `internal/bot/common/handlers/yandex_search.py` — rename import + D3 useHttp2
  rework.
- `internal/services/proxy/lifecycle.py` — rename import.
- `main.py` + `lib/logging_utils.py` — add `httpx2`/`httpcore2` logger silencing (§5).
- Tests: `tests/lib/{geocode_maps,stt/providers/yandex_speechkit,openweathermap,
  yandex_search,ai/providers/basic_openai_provider,aurumentation}` — rename
  imports; add the D2/D3 regression tests.

**NOT in Phase 1:** `internal/bot/telegram/application.py` (PTB — Phase 2).

**Steps:**

1. Write the D3 regression test first (must fail against current code once the
   transport key is gone, pass after the rework).
2. Rework `lib/proxy/__init__.py` (D2); add the D2 unit test.
3. Rename imports across the 13 production files (`import httpx2 as httpx`).
4. Simplify `lib/max_bot/client.py` `_getHttpClient` (remove the
   `"transport" not in proxyKwargs` branch).
5. Apply D3 in `internal/bot/common/handlers/yandex_search.py`.
6. Apply §5 logging changes.
7. Rename test imports; migrate `httpx.MockTransport` → `httpx2.MockTransport`.

**Verification:** `make format lint`; `make test` (full suite — the aurumentation
golden suites are the byte-exact regression net, D6); **manual Минцифры-SSL-through-SOCKS
smoke** (§8 gate, the load-bearing empirical check).

**Gate 1:** owned clients on httpx2; proxy layer simplified; Минцифры CA verified
through the SOCKS tunnel; httpx-socks no longer imported by owned code; PTB
subsystem untouched and still on httpx.

### Phase 2 — PTB decision (independently shippable)

This phase is a **decision point**, not a predetermined implementation. Pick b1
or b2 (D4). Either choice ships on its own.

**If (b1) — keep httpx + httpx-socks for Telegram:**

- Leave `internal/bot/telegram/application.py` on httpx.
- Resolve the PTB-local SOCKS detail (D4 refinement): either keep a local
  `httpx-socks` transport build for PTB, or switch PTB to httpx's native
  `httpx[socks]` `proxy=`. Keep `httpx` + `httpx-socks` pins.
- Document the object-boundary discipline for the Telegram subsystem.

**If (b2) — `alias_httpx()` global rewrite:**

- Add the `httpx2.alias_httpx()` call at the top of `main.py` (§6).
- Remove `httpx` and `httpx-socks` pins from `requirements.direct.txt`;
  regenerate lockfile.
- Run the live Telegram-API smoke pass (§8).

**Verification:** `make format lint`; `make test`; under b2, the **live Telegram
smoke** (getMe / sendMessage round-trip through PTB over the aliased httpx2, with
proxy if configured).

**Gate 2:** PTB subsystem decided and stable; the tree has either one HTTP library
(b2) or two coexisting with documented boundary discipline (b1).

### Phase 3 — Cleanup (only if Phase 2 picked b2)

**Scope:** `requirements.direct.txt`, regenerated `requirements.txt`, docs,
`CHANGELOG.md`.

**Steps:**

1. Remove the `httpx[http2]==0.28.1` pin entirely.
2. Regenerate lockfile; confirm `httpcore` is gone, only `httpcore2` remains.
3. Documentation pass (load the `update-project-docs` skill): update any doc that
   references httpx. Add a `CHANGELOG.md` `Changed` entry under `## [Unreleased]`
   (this is a shipped behavior-preserving migration, so it *does* get a changelog
   entry — unlike these design docs themselves).

**Verification:** `make format lint`; `make test`; `make check-docs`.

**Gate 3:** single HTTP library in the tree; docs in sync.

> If Phase 2 picks b1, Phase 3 is deferred indefinitely (two libraries coexist by
> design). That is an acceptable end state.

---

## 8. Verification gates

| Gate | Command / action | When |
|---|---|---|
| Format + lint | `make format lint` (before AND after edits) | every phase |
| Test suite | `make test` (wrapped in `timeout 5m`) | every phase |
| Docs links | `make check-docs` | Phase 3 (and this doc's own landing) |
| **Минцифры SSL through SOCKS** | manual smoke: owned httpx2 client with `proxy="socks5://..."` + `verify=<Минцифры sslContext>` against a real Минцифры-signed endpoint | **Phase 1 (load-bearing)** |
| HTTP/2-over-SOCKS probe | manual: with SOCKS5 active, check whether `http2=True` now works in httpcore2 | Phase 1 (informs whether D3's guard can drop) |
| Aurumentation golden suites | `make test` (byte-exact replay fixtures) | Phase 1 |
| Live Telegram smoke | manual: PTB getMe/sendMessage round-trip | Phase 2 **only if b2** |

The Минцифры-SSL-through-SOCKS smoke is the single most important empirical check:
it is the one place where "httpx2 is a drop-in fork" could still bite, because the
SSL/truststore change (research doc §4.2) intersects the custom CA trust path.

---

## 9. Risk register + rollback

| Risk | Likelihood | Impact | Mitigation | Rollback |
|---|---|---|---|---|
| **Object boundary** — an httpx object crosses into httpx2-typed code (or vice versa); `isinstance`/`except` fails | Med | Med | D5 convention; b1 isolates PTB; review for cross-subsystem object passing | Revert the offending file |
| **Минцифры SSL through SOCKS** — `verify=` does not reach target TLS under native `proxy="socks5://"` | Med | **High** | Empirical smoke (§8) is a Phase 1 gate; httpcore2 #869/#880 fixes suggest it works | Revert Phase 1 proxy rework; keep `httpx-socks` transport |
| **truststore SSL divergence** — httpx2's OS-trust-store switch changes cert resolution (affects b2 + custom CAs) | Med | High | b1 avoids it entirely; b2 gets a dedicated Telegram+SSL smoke | Choose b1 |
| **Early adoption / ecosystem bifurcation** — httpx2 stalls or diverges; two libs persist | Low | Med | Incremental plan; httpx stays until Phase 3; deferral is always an option | Stop at Phase 0/1 |
| **PTB-specific (b2)** — `alias_httpx()` global rewrite breaks PTB cert handling or object identity | Med | High | b2 is a time-boxed spike with a live smoke gate; b1 is the default | Fall back to b1 |
| **Aurumentation golden drift** — httpx2 serialization differs byte-for-byte | Low | Low | Golden suites are the regression net; a drift is a finding, not a silent regen | Revert; regenerate deliberately |
| **HTTP/2-over-SOCKS regression** — D3 rework silently re-enables HTTP/2 over SOCKS | Med | Med | Regression test (D7) keyed on `proxyType`; smoke probe (§8) | Restore guard |

**Rollback principle:** every phase is independently revertible via git. Keeping
the `httpx` pin until Phase 3 means Phase 1 + Phase 2(b1) can run with both
libraries present, so a partial rollback never leaves the tree without a working
HTTP library.

---

## 10. Open questions

1. **PTB: b1 vs b2 (D4).** Explicitly left to the user. Recommended default is b1
   (lowest risk); b2 is a time-boxed spike. This is the Phase 2 decision point.
2. **HTTP/2-over-SOCKS in httpcore2.** Does it now work? If yes, D3's guard can be
   dropped. Resolve via the §8 probe during Phase 1.
3. **PTB-local SOCKS under b1.** Once `toKwargs()` no longer emits a transport,
   the Telegram wiring must either build its own `httpx-socks` transport locally
   or switch PTB to `httpx[socks]` native `proxy=`. Resolve during the Phase 2 b1
   spike.
4. **sqlink.** The `sqlink` git dependency uses httpx internally with its own
   `proxy=` param. Confirm it is unaffected by the owned-code migration (expected:
   yes — it has its own client). Verify during Phase 1.

---

## 11. Documentation impact

When implementation lands, load the `update-project-docs` skill and update:

- [`docs/llm/libraries.md`](../llm/libraries.md) — note the httpx → httpx2 swap in
  `lib/proxy`, `lib/max_bot`, `lib/aurumentation`, and the AI/STT/search clients.
- [`docs/llm/architecture.md`](../llm/architecture.md) — note the dependency change
  and (if b2) the `alias_httpx()` startup hook.
- [`docs/developer-guide.md`](../developer-guide.md) — any httpx references in
  examples (verified: lines ~1852, ~2375 reference `import httpx`).
- [`docs/design/httpx2-migration-research.md`](./httpx2-migration-research.md) —
  mark adopted/deferred items as the phases land.
- `CHANGELOG.md` — a `Changed` entry when the migration actually ships (Phase 1
  and/or Phase 3). These design docs themselves get **no** changelog entry (per
  AGENTS.md: doc-only, no shipped feature).

---

## 12. References

- Research doc: [`httpx2-migration-research.md`](./httpx2-migration-research.md)
- httpx2 migration guide: https://httpx2.pydantic.dev/migration/ (accessed 2026-08-13)
- httpx2 proxies: https://httpx2.pydantic.dev/advanced/proxies/ (accessed 2026-08-13)
- httpx2 CHANGELOG: https://github.com/pydantic/httpx2/blob/main/src/httpx2/CHANGELOG.md (accessed 2026-08-13)
- httpx-socks HTTP/2 issue: https://github.com/romis2012/httpx-socks/issues/2 (accessed 2026-08-13)
