# Max Messenger Bot API Migration Plan

> **Status:** READY FOR IMPLEMENTATION
> **Last updated:** 2026-06-29
> **Deadline:** 2026-07-19 (20 days)
> **Affected module:** `lib/max_bot/` (library), `internal/bot/max/` (application)

---

## Table of Contents

1. [Motivation](#1-motivation)
2. [Current State Summary](#2-current-state-summary)
3. [Implementation Plan](#3-implementation-plan)
4. [Risk Assessment](#4-risk-assessment)
5. [Testing Strategy](#5-testing-strategy)
6. [Documentation Impact](#6-documentation-impact)
7. [Open Questions](#7-open-questions)

---

## 1. Motivation

Max Messenger is deprecating the `platform-api.max.ru` endpoint in favour of
`platform-api2.max.ru`. All bots must migrate by **July 19, 2026**. After that
date, requests to the old endpoint will fail and the bot will stop functioning
in Max mode.

The new endpoint additionally requires trust for the **Russian Ministry of
Digital Development (Минцифры) root CA chain**, which is not present in
standard OS/certifi CA bundles. Without explicitly trusting these certificates,
`httpx` will raise `ssl.SSLCertVerificationError` on every request to
`platform-api2.max.ru`.

### What breaks if we do nothing

- After 2026-07-19 the old endpoint stops responding → `MaxBotClient` throws
  `NetworkError` on every API call → the Max bot is completely offline.
- Even if we flip the URL today without the cert fix, TLS handshake failures
  will prevent all API communication.

### What does NOT change

- Authentication: the raw `Authorization: <token>` header (no `Bearer` prefix)
  is already correct for `platform-api2`.
  See `lib/max_bot/client.py:213`.
- API contract: the endpoint paths (`/me`, `/messages`, `/updates`, etc.)
  remain identical.
- Long-polling behaviour: unchanged.

---

## 2. Current State Summary

### Files involved

| File | Relevance |
|---|---|
| `lib/max_bot/constants.py` | `API_BASE_URL` (line 16), `DEFAULT_RATE_LIMIT` (line 39), commented-out `platform-api2` URL (line 15) |
| `lib/max_bot/client.py` | `MaxBotClient.__init__` accepts `baseUrl` (line 124), creates `httpx.AsyncClient` in `_getHttpClient` (line 199). **No `verify=` parameter.** |
| `internal/bot/max/application.py` | Instantiates `MaxBotClient` at line 289 with default `baseUrl`. No TLS config. |
| `configs/00-defaults/00-config.toml` | Bot config section. No Max-specific TLS settings. |
| `lib/proxy/__init__.py` | `ProxyConfig.toKwargs()` returns kwargs spread into `httpx.AsyncClient`. Does not touch `verify=`. |

### Current endpoint and TLS config

- `API_BASE_URL = "https://platform-api.max.ru"` (active, line 16).
- `"https://platform-api2.max.ru"` commented out on line 15 — someone
  anticipated this migration.
- `"https://botapi.max.ru"` commented out on line 17 — legacy endpoint.
- **Zero TLS configuration** anywhere in the Max client, Max application, or
  TOML configs. The `httpx.AsyncClient` relies entirely on system/certifi
  defaults.

### Rate limit difference

- Current constant: `DEFAULT_RATE_LIMIT = 100` (line 39).
- New API enforces **30 rps** (vs. 100 on the old endpoint).

### Deprecated endpoints

- `GET /chats` is deprecated as of June 2026 on the new API. The client has
  `getChats()` (line 499), but `grep` confirms it is **not called** anywhere
  in `internal/` — no immediate action required beyond a deprecation comment.

---

## 3. Implementation Plan

### Step 1: Store Минцифры CA certificates in the repo

**What:** Download and commit the two PEM files from the Russian government
CA distribution point.

**Where:** Create directory `certs/max/` at repo root.

**Files to add:**

```
certs/max/russian_trusted_root_ca.pem    # Russian Trusted Root CA
certs/max/russian_trusted_sub_ca.pem     # Russian Trusted Sub CA
```

**How to obtain:**

Download from `https://www.gosuslugi.ru/crt`:
- "Russian Trusted Root CA" → `russian_trusted_root_ca_pem.crt`
- "Russian Trusted Sub CA" → `russian_trusted_sub_ca_pem.crt`

Rename to `.pem` extension for clarity. These are standard PEM files (ASCII
`-----BEGIN CERTIFICATE-----` blocks).

**Verification:** After downloading, verify the files are valid PEM:

```python
# Quick validation script (do not run via python -c; write a script file per AGENTS.md)
import ssl
ctx = ssl.create_default_context()
ctx.load_verify_locations("certs/max/russian_trusted_root_ca.pem")
ctx.load_verify_locations("certs/max/russian_trusted_sub_ca.pem")
print("Certs loaded OK")
```

**Rationale for committing to repo:** These are public government-issued CA
certificates, not secrets. Committing them avoids a runtime download dependency
on `gosuslugi.ru` and makes builds reproducible. The alternative (system-level
install) is fragile across deployment targets (Docker, macOS, various Linux
distros).

---

### Step 2: Add CA bundle path to TOML configuration

**What:** Add a `ca-bundle` key under `[bot]` in the defaults config, so the
path to the certificate directory is configurable. Defaults to `certs/max/`
relative to repo root.

**Where:** `configs/00-defaults/00-config.toml`

**Change:** Add inside the existing `[bot]` section, after the proxy block:

```toml
[bot]
# ...existing keys...

# --- Max API TLS ---
# Path to directory containing additional CA certificates for Max Messenger
# API (platform-api2.max.ru). Required because the new endpoint uses
# certificates issued by the Russian Минцифры CA, which is not in standard
# CA bundles. Path is relative to the application root directory.
# Set to empty string to use system defaults (not recommended for Max mode).
max-ca-bundle = "certs/max"
```

**Why a directory path, not a single file:** httpx supports `verify=` with a
path to a directory of PEM files (via `ssl.create_default_context()` +
`load_verify_locations(capath=...)`). However, `capath` requires the directory
to contain hash-symlinks (via `c_rehash`), which is fragile. Instead, the
implementation will concatenate all `.pem` files in the directory into a
combined bundle at startup and use `verify=<combined_path>` or build an
`ssl.SSLContext`. See Step 4 for the exact approach.

**Alternative considered:** A single combined PEM file path. This is simpler
but less maintainable — when certificates rotate, operators must rebuild the
combined file. A directory of individual PEM files is operationally cleaner.

---

### Step 3: Update `API_BASE_URL` and rate limit constants

**Where:** `lib/max_bot/constants.py`

**Changes:**

```python
# API Configuration
# Old endpoints (deprecated, will stop working after 2026-07-19):
#   - https://platform-api.max.ru  — original endpoint
#   - https://botapi.max.ru        — legacy endpoint
API_BASE_URL: Final[str] = "https://platform-api2.max.ru"
API_VERSION: Final[str] = "0.0.1"
DEFAULT_TIMEOUT: Final[int] = 30
MAX_RETRIES: Final[int] = 5
RETRY_BACKOFF_FACTOR: Final[float] = 1.0
```

This replaces lines 14–21. The three commented-out URL lines (15, 16, 17) are
replaced with the new active URL and a comment documenting the deprecated ones.

**Rate limit:**

```python
# Rate Limiting
# NOTE: platform-api2.max.ru enforces 30 rps (down from 100 on platform-api.max.ru)
DEFAULT_RATE_LIMIT: Final[int] = 30  # requests per second
RATE_LIMIT_WINDOW: Final[int] = 1  # second
```

This replaces lines 38–40.

**Deprecation comment on `getChats`:**

In `lib/max_bot/client.py`, add a deprecation notice to the `getChats` method
docstring (around line 499):

```python
    async def getChats(self, count: int = 50, marker: Optional[int] = None) -> ChatList:
        """Get list of chats where the bot participated.

        .. deprecated:: June 2026
            GET /chats is deprecated on platform-api2.max.ru.
            This method may stop working after the migration deadline.

        ...existing docstring...
        """
```

---

### Step 4: Add TLS verification to `MaxBotClient`

This is the core change. The approach: build an `ssl.SSLContext` that trusts
both the system/certifi CAs **and** the Минцифры certificates, then pass it
to `httpx.AsyncClient(verify=sslContext)`.

#### 4.1 Add `sslContext` parameter to `MaxBotClient.__init__`

**Where:** `lib/max_bot/client.py`

**What:** Add an optional `sslContext` parameter. When provided, it is passed
as `verify=` to `httpx.AsyncClient`. When `None`, httpx uses its defaults
(system CAs).

Add to `__slots__`:

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
        "_proxyConfig",
        "_sslContext",  # NEW
    )
```

Add to `__init__` signature:

```python
    def __init__(
        self,
        accessToken: str,
        baseUrl: str = API_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        maxRetries: int = MAX_RETRIES,
        retryBackoffFactor: float = RETRY_BACKOFF_FACTOR,
        proxyConfig: Optional[ProxyConfig] = None,
        sslContext: Optional[ssl.SSLContext] = None,  # NEW
    ) -> None:
```

Add import at top of file:

```python
import ssl
```

Store in `__init__`:

```python
        self._sslContext: Optional[ssl.SSLContext] = sslContext
```

Update docstring `Attributes:` section to document the new parameter.

#### 4.2 Pass `verify=` in `_getHttpClient`

**Where:** `lib/max_bot/client.py`, `_getHttpClient` method (line 186)

**Current code (line 199):**

```python
            httpClient = httpx.AsyncClient(
                **self._proxyConfig.toKwargs(),
                base_url=self.baseUrl,
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "User-Agent": f"Gromozeka/{VERSION}",
                },
            )
```

**New code:**

```python
            clientKwargs: Dict[str, Any] = {
                **self._proxyConfig.toKwargs(),
                "base_url": self.baseUrl,
                "timeout": httpx.Timeout(self.timeout),
                "headers": {
                    "User-Agent": f"Gromozeka/{VERSION}",
                },
            }
            if self._sslContext is not None:
                clientKwargs["verify"] = self._sslContext
            httpClient = httpx.AsyncClient(**clientKwargs)
```

**Why conditional:** When `sslContext is None`, we omit `verify=` entirely so
httpx uses its default (`certifi` bundle). This keeps non-Max usage (tests,
other consumers of the library) working unchanged. It also means Telegram mode
is completely unaffected.

#### 4.3 Also apply `verify=` to `getNew=True` clients

The `uploadFile` method (line 1542) and `downloadAttachmentPayload` method
(line 1622) call `_getHttpClient(getNew=True)`, which creates a fresh
`httpx.AsyncClient`. The change in 4.2 already covers this since both paths
go through the same `_getHttpClient` code.

Verify: confirm that all `httpx.AsyncClient` construction in `client.py` goes
through `_getHttpClient`. It does — there are no other `httpx.AsyncClient()`
calls in the file.

---

### Step 5: Build `SSLContext` at application startup

**Where:** `internal/bot/max/application.py`

**What:** Before constructing `MaxBotClient`, build an `ssl.SSLContext` from
the configured CA bundle path. Pass it to the client constructor.

**New helper function** (add as a module-level function in
`internal/bot/max/application.py`, or as a utility in `lib/max_bot/`):

Since the SSL context building is specific to the Max bot client's needs and
involves no `internal/` dependencies, place it in `lib/max_bot/` as a new
utility. Add to `lib/max_bot/utils.py` (which already exists but currently
has other utilities):

```python
import ssl
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def buildMaxSslContext(caBundlePath: Optional[str] = None) -> Optional[ssl.SSLContext]:
    """Build an SSL context that trusts both system CAs and custom CA certificates.

    Loads the default system/certifi CA bundle, then loads any additional PEM
    certificate files found in the specified directory. This is needed for
    platform-api2.max.ru, which uses certificates issued by the Russian
    Минцифры CA that are not in standard CA bundles.

    Args:
        caBundlePath: Path to a directory containing additional PEM certificate
            files (.pem, .crt). If None or empty string, returns None (use
            system defaults). Path is resolved relative to the current working
            directory.

    Returns:
        An ssl.SSLContext with system CAs + custom CAs loaded, or None if
        no custom CA path was provided.

    Raises:
        FileNotFoundError: If the specified directory does not exist.
        ssl.SSLError: If a certificate file is malformed.
    """
    if not caBundlePath:
        return None

    certDir = Path(caBundlePath)
    if not certDir.is_dir():
        raise FileNotFoundError(
            f"Max CA bundle directory not found: {certDir.resolve()}. "
            f"Download certificates from https://www.gosuslugi.ru/crt"
        )

    # Start with system defaults (loads certifi or OS CA bundle)
    ctx = ssl.create_default_context()

    # Load each PEM file from the directory
    loaded = 0
    for certFile in sorted(certDir.iterdir()):
        if certFile.suffix in (".pem", ".crt") and certFile.is_file():
            ctx.load_verify_locations(cafile=str(certFile))
            logger.info("Loaded CA certificate: %s", certFile.name)
            loaded += 1

    if loaded == 0:
        logger.warning(
            "No .pem/.crt files found in %s. TLS connections to "
            "platform-api2.max.ru may fail.",
            certDir.resolve(),
        )
        return None

    logger.info("SSL context ready with %d additional CA certificate(s)", loaded)
    return ctx
```

**Update the call site** in `internal/bot/max/application.py` (around line 289):

```python
        # --- Proxy support ---
        botConfig = self.configManager.getBotConfig()
        proxyConfig = ProxyService.getInstance().resolveProxy(botConfig, "max-bot")
        maskedUrl = proxyConfig.getProxyURL(maskPassword=True)
        if maskedUrl:
            logger.info("Proxy enabled for Max bot: %s", maskedUrl)

        # --- TLS: trust Минцифры CA for platform-api2.max.ru ---
        caBundlePath = botConfig.get("max-ca-bundle", "")
        sslContext = libMax.utils.buildMaxSslContext(caBundlePath) if caBundlePath else None

        self.maxBot = libMax.MaxBotClient(
            self.botToken,
            proxyConfig=proxyConfig,
            sslContext=sslContext,
        )
```

Add import at top of `application.py`:

```python
from lib.max_bot import utils as maxBotUtils
```

Or alternatively import inline via the already-imported `libMax`:

```python
import lib.max_bot as libMax
# then use: libMax.utils.buildMaxSslContext(...)
```

The latter is cleaner since `lib.max_bot` is already imported as `libMax` on
line 12. Ensure `lib/max_bot/utils.py` exports `buildMaxSslContext` (it will,
being a module-level function).

---

### Step 6: Update `MaxBotClient` docstring

Update the class-level docstring in `lib/max_bot/client.py` (line 79) to
reflect the new `sslContext` attribute:

```python
    Attributes:
        accessToken: The bot access token for API authentication
        baseUrl: Base URL for the API (default: https://platform-api2.max.ru)
        timeout: Request timeout in seconds (default: 30)
        maxRetries: Maximum number of retry attempts (default: 5)
        retryBackoffFactor: Backoff factor for retry delays (default: 1.0)
        sslContext: Optional SSL context for custom CA trust (e.g. Минцифры CA)
```

---

## 4. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Certificates expire or rotate** | Low (root CAs have 10+ year validity) | High — TLS failures | Monitor cert expiry; add a startup warning if any cert expires within 90 days. Document re-download procedure. |
| **`platform-api2` endpoint is unreachable from deployment network** | Medium (network/firewall) | High — bot offline | Test connectivity to `platform-api2.max.ru:443` from the deployment host before deploying. Add a health check log line on startup (`getMyInfo()` already serves this purpose — line 292). |
| **`ssl.create_default_context()` does not load certifi on some platforms** | Low | Medium — system CAs missing | httpx and Python's ssl module both use certifi when available. The cert bundle is additive, so even if certifi is missing, the Минцифры certs will be loaded. |
| **Rate limit drop from 100→30 rps causes throttling** | Medium | Low — existing usage is well below 30 rps for a single bot | Update `DEFAULT_RATE_LIMIT` constant. The existing retry logic with exponential backoff in `_makeRequest` (line 309–313) handles `RateLimitError` correctly. |
| **`getChats()` deprecation breaks something** | Very Low — not called | None | Add deprecation comment. No code changes needed. |
| **Proxy + custom SSL context interaction** | Low | Medium | httpx handles `verify=` and `proxy=`/`transport=` independently. When using SOCKS5 transport, the `verify=` parameter still applies to the TLS handshake with the target server. Test both proxy and non-proxy configurations. |
| **`getNew=True` clients for uploads/downloads miss SSL context** | None (code path covered) | High if missed | Verified: all `httpx.AsyncClient` construction goes through `_getHttpClient()`. The change in Step 4.2 applies to all clients. |

---

## 5. Testing Strategy

### 5.1 Unit tests (no network, no real token)

Create `tests/lib/max_bot/test_client.py` (no Max bot tests exist today):

**Test 1: `API_BASE_URL` constant value**

```python
def testApiBaseUrlIsNewEndpoint():
    """Verify API_BASE_URL points to platform-api2.max.ru."""
    from lib.max_bot.constants import API_BASE_URL
    assert API_BASE_URL == "https://platform-api2.max.ru"
```

**Test 2: `DEFAULT_RATE_LIMIT` constant value**

```python
def testDefaultRateLimitIs30():
    """Verify DEFAULT_RATE_LIMIT reflects the new API's 30 rps limit."""
    from lib.max_bot.constants import DEFAULT_RATE_LIMIT
    assert DEFAULT_RATE_LIMIT == 30
```

**Test 3: SSL context is passed through to httpx client**

```python
async def testSslContextPassedToHttpClient():
    """Verify that sslContext parameter reaches httpx.AsyncClient."""
    import ssl
    from unittest.mock import patch, MagicMock
    from lib.max_bot.client import MaxBotClient

    ctx = ssl.create_default_context()
    client = MaxBotClient("test-token", sslContext=ctx)

    with patch("httpx.AsyncClient") as mockAsyncClient:
        mockAsyncClient.return_value = MagicMock()
        mockAsyncClient.return_value.is_closed = False
        mockAsyncClient.return_value.headers = {}
        client._getHttpClient()

        # Verify verify= was passed
        callKwargs = mockAsyncClient.call_args
        assert callKwargs.kwargs.get("verify") is ctx or \
               (len(callKwargs.args) == 0 and "verify" in str(callKwargs))
```

**Test 4: No SSL context when None**

```python
async def testNoSslContextWhenNone():
    """Verify that verify= is NOT passed when sslContext is None."""
    from unittest.mock import patch, MagicMock
    from lib.max_bot.client import MaxBotClient

    client = MaxBotClient("test-token", sslContext=None)

    with patch("httpx.AsyncClient") as mockAsyncClient:
        mockAsyncClient.return_value = MagicMock()
        mockAsyncClient.return_value.is_closed = False
        mockAsyncClient.return_value.headers = {}
        client._getHttpClient()

        callKwargs = mockAsyncClient.call_args.kwargs
        assert "verify" not in callKwargs
```

**Test 5: `buildMaxSslContext` with valid directory**

```python
def testBuildMaxSslContextLoadsFromDirectory(tmp_path):
    """Verify buildMaxSslContext loads PEM files from a directory."""
    import ssl
    from lib.max_bot.utils import buildMaxSslContext

    # Create a dummy self-signed cert for testing
    # (Use a fixture or a pre-generated test cert)
    certContent = _generateSelfSignedCert()  # helper
    certFile = tmp_path / "test_ca.pem"
    certFile.write_text(certContent)

    ctx = buildMaxSslContext(str(tmp_path))
    assert ctx is not None
    assert isinstance(ctx, ssl.SSLContext)
```

**Test 6: `buildMaxSslContext` with missing directory**

```python
def testBuildMaxSslContextMissingDirectory():
    """Verify FileNotFoundError when CA bundle directory doesn't exist."""
    from lib.max_bot.utils import buildMaxSslContext
    import pytest

    with pytest.raises(FileNotFoundError, match="Max CA bundle directory not found"):
        buildMaxSslContext("/nonexistent/path")
```

**Test 7: `buildMaxSslContext` with empty/None returns None**

```python
def testBuildMaxSslContextEmptyPathReturnsNone():
    """Verify None return when path is empty or None."""
    from lib.max_bot.utils import buildMaxSslContext

    assert buildMaxSslContext(None) is None
    assert buildMaxSslContext("") is None
```

### 5.2 Integration smoke test (requires connectivity, optional)

Not suitable for CI, but the implementer should verify manually:

```bash
# From the deployment host, verify TLS handshake works with the new certs:
./venv/bin/python3 -c "
import ssl, socket
ctx = ssl.create_default_context()
ctx.load_verify_locations('certs/max/russian_trusted_root_ca.pem')
ctx.load_verify_locations('certs/max/russian_trusted_sub_ca.pem')
with ctx.wrap_socket(socket.socket(), server_hostname='platform-api2.max.ru') as s:
    s.connect(('platform-api2.max.ru', 443))
    print('TLS OK:', s.version())
"
```

**Note:** The above is for manual verification only. Per AGENTS.md, do not use
`python -c` in automation — write a script file if this needs to be repeatable.

### 5.3 Existing test compatibility

Run `make test` to confirm no regressions. The constant changes
(`API_BASE_URL`, `DEFAULT_RATE_LIMIT`) should not break existing tests since
there are no Max bot tests today. If any test imports these constants, verify
they still pass with the new values.

---

## 6. Documentation Impact

| Change | Documents to update |
|---|---|
| New config key `max-ca-bundle` | `docs/llm/configuration.md` — add to bot config section |
| API endpoint change | `docs/llm/libraries.md` — update Max bot library description |
| Rate limit change | `docs/llm/libraries.md` — note the 30 rps limit |
| New `certs/max/` directory | `docs/llm/architecture.md` or `docs/llm/index.md` — mention in directory layout |
| New parameter on `MaxBotClient` | `docs/llm/libraries.md` — update MaxBotClient API description |
| New function in `lib/max_bot/utils.py` | `docs/llm/libraries.md` — document `buildMaxSslContext` |

Use the `update-project-docs` skill after implementation to ensure all docs
are synced.

---

## 7. Open Questions

### Q1: Should the cert files be committed to the repo?

**Recommendation:** Yes. These are public government-issued CA certificates,
not secrets. Committing them ensures reproducible builds and avoids a runtime
dependency on `gosuslugi.ru` availability. Add them to `certs/max/` as
described in Step 1.

**Alternative:** Require operators to install them system-wide or provide a
path via config. This is more fragile and harder to document.

### Q2: Should we support a combined PEM file as an alternative?

**Recommendation:** The implementation in Step 5 already handles this — if the
operator provides a directory with a single combined `.pem` file, it works.
No special handling needed.

### Q3: Should `buildMaxSslContext` live in `lib/max_bot/utils.py` or elsewhere?

**Recommendation:** `lib/max_bot/utils.py` — it is specific to the Max bot
client's needs and has no `internal/` dependencies. The file already exists
for Max bot utilities.

### Q4: Should we add a startup health check against platform-api2?

**Recommendation:** No additional work needed. The existing flow already calls
`getMyInfo()` immediately after constructing the client
(`application.py:292`). If TLS fails, the error will surface immediately at
startup rather than silently failing later.

### Q5: Do we need to worry about the cert path at test time?

**Recommendation:** No. Tests that construct `MaxBotClient` directly will pass
`sslContext=None` (or omit it), which preserves the current behaviour of using
system defaults. The SSL context is only built when the application starts in
Max mode and the config provides a `max-ca-bundle` path. Tests that mock
`httpx.AsyncClient` are completely unaffected.

### Q6: What about `lib/max_bot/client.py` upload/download methods that create fresh clients?

**Verified:** `uploadFile` (line 1542) and `downloadAttachmentPayload`
(line 1622) both use `_getHttpClient(getNew=True)`, which goes through the
same code path as the main client. The SSL context change in Step 4.2 covers
these automatically.

---

## Implementation Checklist

For the `software-developer` agent:

- [ ] Download and commit Минцифры CA certificates to `certs/max/`
- [ ] Add `max-ca-bundle` config key to `configs/00-defaults/00-config.toml`
- [ ] Update `API_BASE_URL` in `lib/max_bot/constants.py`
- [ ] Update `DEFAULT_RATE_LIMIT` to 30 in `lib/max_bot/constants.py`
- [ ] Add deprecation comment to `getChats()` in `lib/max_bot/client.py`
- [ ] Add `import ssl` to `lib/max_bot/client.py`
- [ ] Add `_sslContext` to `MaxBotClient.__slots__`, `__init__`, and docstring
- [ ] Update `_getHttpClient` to pass `verify=self._sslContext` when not None
- [ ] Add `buildMaxSslContext()` to `lib/max_bot/utils.py`
- [ ] Update `internal/bot/max/application.py` to build and pass SSL context
- [ ] Write tests in `tests/lib/max_bot/test_client.py`
- [ ] Run `make format lint`
- [ ] Run `make test`
- [ ] Update documentation (use `update-project-docs` skill)
