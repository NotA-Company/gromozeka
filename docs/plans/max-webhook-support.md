# Max Messenger Webhook Support -- Implementation Plan

> **Status:** READY FOR IMPLEMENTATION
> **Last updated:** 2025-06-30
> **Scope:** Two-process architecture -- external webhook receiver acts as a local Max API proxy; bot polls the receiver via `GET /updates`

---

## Table of Contents

1. [Motivation](#1-motivation)
2. [Architecture Overview](#2-architecture-overview)
3. [Part A: Webhook Receiver](#3-part-a-webhook-receiver)
4. [Part B: Bot-Side Changes](#4-part-b-bot-side-changes)
5. [Part C: Database Schema](#5-part-c-database-schema)
6. [Part D: Configuration](#6-part-d-configuration)
7. [Implementation Sequence](#7-implementation-sequence)
8. [Testing Strategy](#8-testing-strategy)
9. [Risk Assessment](#9-risk-assessment)
10. [Resolved Decisions](#10-resolved-decisions)
11. [Open Questions](#11-open-questions)
12. [Documentation Impact](#12-documentation-impact)

---

## 1. Motivation

### Why webhooks over long-polling

Max Messenger's long-polling endpoint (`GET /updates`) is explicitly documented
as **not suitable for production**: it is rate-limited and events expire quickly.
The Max API cannot serve both polling and webhooks simultaneously for a given bot
-- activating webhooks disables polling, and vice versa.

Webhooks provide:

- **Reliability.** Max retries delivery up to 10 times with exponential backoff
  (60 s -> 150 s -> 375 s -> ..., x2.5) over an 8-hour window.  With polling,
  if the bot is down for more than a few minutes, events are silently lost.
- **Latency.** Events arrive as soon as Max processes them, rather than on the
  next poll cycle (up to 30 s timeout).
- **Reduced API load.** No continuous `GET /updates` requests against the real
  Max API; only real events generate traffic.

### Design constraint

The user explicitly does **not** want a web server embedded in the bot process.
Instead, the architecture separates concerns:

1. A **small, standalone webhook receiver** -- a separate process that accepts
   HTTPS POSTs from Max, verifies their origin, writes raw update JSON into
   a local SQLite table, **and** exposes a `GET /updates` endpoint that speaks
   the same protocol as the real Max API.
2. The **bot process** polls the receiver's `GET /updates` endpoint instead of
   `platform-api2.max.ru`.  The bot's existing `MaxBotClient._pollingLoop()`
   is completely reused -- only the base URL changes.

This keeps the bot's architecture unchanged (single-process, async, no web
framework embedded, no new polling logic) while gaining all webhook benefits.

---

## 2. Architecture Overview

```
                    HTTPS POST (Update JSON)
  ┌────────────┐   ────────────────────────────>   ┌─────────────────────────┐
  │  Max API   │                                   │  Webhook Receiver       │
  │ (platform- │   <── HTTP 200 ──────────────     │  (separate process)     │
  │  api2.max  │                                   │                         │
  │   .ru)     │                                   │  POST /webhook          │
  └──────┬─────┘                                   │   -> verify secret      │
         │                                         │   -> store to SQLite    │
         │                                         │                         │
         │  POST /subscriptions (startup)          │  GET /updates           │
         │  DELETE /subscriptions (shutdown)        │   -> read from SQLite   │
         │    <────────────────────────────────     │   -> return Max-format  │
         │                                         │      JSON               │
         │                                         │   -> mark as processed  │
  ┌──────┴────────────┐                            └────────────┬────────────┘
  │   Gromozeka Bot   │                                         │
  │  (MaxBotApp)      │    GET /updates?marker=X&limit=Y        │
  │                   │   ──────────────────────────────────>    │
  │  _pollingLoop()   │                                         │
  │  (unchanged)      │   <── {"updates":[...],"marker":"Z"} ── │
  └───────────────────┘
```

**Key points:**

- The webhook receiver and the bot are **separate OS processes**, started
  independently (e.g., systemd, supervisor, docker-compose).
- They share a single SQLite database file.  SQLite supports concurrent readers
  and a single writer with WAL mode -- both processes can operate safely.
- The receiver acts as a **local Max API proxy**: it exposes `GET /updates`
  returning JSON identical to what `platform-api2.max.ru` returns.  The bot's
  `MaxBotClient._pollingLoop()` (at `lib/max_bot/client.py:1280-1349`)
  sees no difference.
- The bot's only change is a **URL override**: when `webhook-receiver.enabled`
  is true, `MaxBotClient` is constructed with `basePollingUrl` pointing to
  the receiver's localhost address instead of `API_BASE_URL`.
- The bot continues to call the **real** Max API for webhook subscription
  management (`POST /subscriptions`, `DELETE /subscriptions`) via the
  existing `setWebhook()` / `deleteWebhook()` methods.
- The `maxHandler()` method at `internal/bot/max/application.py:160-246` is
  **completely unchanged** -- it receives `Update` objects regardless of source.

---

## 3. Part A: Webhook Receiver

### 3.1 Technology Choice

**Recommendation: `aiohttp.web`** (the server component of `aiohttp`).

Rationale:

| Option | Pros | Cons |
|--------|------|------|
| **`aiohttp.web`** (recommended) | Already a transitive dependency (`aiodocker` -> `aiohttp==3.14.1` in `requirements.txt:4`). Async-native. Minimal, well-understood. No new paradigm -- the project is async-first. Server and client in one package. | Slightly more boilerplate than FastAPI, but this is a ~150-line server. |
| `starlette` + `uvicorn` | Lightweight, ASGI. | Two new dependencies. No existing usage in the project. |
| `http.server` (stdlib) | Zero deps. | Synchronous. No async. No TLS support without wrapping. |
| `FastAPI` | Rich, popular. | Pulls in Pydantic -- explicitly forbidden by `AGENTS.md`. Overkill for two endpoints. |

**Dependency note:** `aiohttp==3.14.1` is currently a **transitive** dependency
via `aiodocker==0.27.0`.  It is NOT in `requirements.direct.txt`.  Once the
receiver imports `aiohttp` directly, it **must** be added to
`requirements.direct.txt` under `# Runtime` with version pin
`aiohttp==3.14.1`.  This makes the dependency explicit and prevents silent
breakage if `aiodocker` is ever removed.

### 3.2 File Location

```
internal/
  max_webhook_receiver/
    __init__.py          # package init
    app.py               # aiohttp.web Application, routes, startup/shutdown
    config.py            # WebhookReceiverConfig TypedDict, TOML loading
    __main__.py          # entry point: `python3 -m internal.max_webhook_receiver`
```

The receiver lives under `internal/` because it depends on `internal/database/`
infrastructure.  It is **not** in `lib/` because it has bot-internal
dependencies (database repos, config manager).

### 3.3 POST /webhook -- Request Verification Flow

```
  POST /webhook  (or configurable path)
       │
       ▼
  ┌─ Check X-Max-Bot-Api-Secret header ──┐
  │   header == configured secret?       │
  │   No  ──> 403 Forbidden (log warn)   │
  │   Yes ──> continue                   │
  └──────────────────────────────────────┘
       │
       ▼
  ┌─ Parse JSON body ────────────────────┐
  │   json.loads(body)                   │
  │   Malformed ──> 400 Bad Request      │
  │   OK ──> extract update_type         │
  └──────────────────────────────────────┘
       │
       ▼
  ┌─ Store to DB ───────────────────────┐
  │   INSERT INTO webhook_updates       │
  │   (id, received_at, update_type,    │
  │    raw_json, processed)             │
  │   VALUES (uuid, now, type, json, 0) │
  └─────────────────────────────────────┘
       │
       ▼
  Return HTTP 200 (empty body)
```

**Secret comparison** must use `hmac.compare_digest()` to prevent timing
side-channel attacks:

```python
import hmac

def verifySecret(headerValue: str, expectedSecret: str) -> bool:
    """Constant-time comparison of webhook secret.

    Args:
        headerValue: Value from X-Max-Bot-Api-Secret header.
        expectedSecret: Configured secret string.

    Returns:
        True if secrets match.
    """
    return hmac.compare_digest(headerValue.encode(), expectedSecret.encode())
```

**DB write failure policy (decided):** Return HTTP 200 and log the error.  Do
not return 500 -- that would trigger Max retries which may cause duplicates.
DB write failures should be extremely rare with SQLite.

### 3.4 GET /updates -- Local Polling Endpoint

This is the core of the new architecture.  The receiver exposes a
`GET /updates` endpoint that speaks the **exact same protocol** as the real
Max API at `platform-api2.max.ru/updates`.  The bot's
`MaxBotClient._pollingLoop()` calls this endpoint with the same query
parameters and expects the same response format.

#### 3.4.1 Request Format

```
GET /updates?marker=<opaque>&limit=100&timeout=30
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `marker` | string | No | Opaque cursor from previous response. If absent, return all unprocessed updates. |
| `limit` | int | No | Max updates to return (default 100, clamped to 1-1000 to match Max API). |
| `timeout` | int | No | Long-polling timeout in seconds (default 30, clamped to 0-90). If no updates are available, hold the connection up to `timeout` seconds, periodically re-checking, then return empty. |

**Note on `types` parameter:** The real Max API accepts a `types` query parameter
to filter update types.  The receiver ignores this -- all stored updates are
returned regardless of type.  Type filtering was already done at the webhook
subscription level (the `webhook-update-types` config controls which types
Max sends).

#### 3.4.2 Response Format

JSON matching the Max API format exactly, as parsed by
`UpdateList.from_dict()` (`lib/max_bot/models/update.py:1251-1324`):

```json
{
  "updates": [
    {
      "update_type": "message_created",
      "timestamp": 1234567890,
      "message": {"...": "..."}
    }
  ],
  "marker": "<next-cursor>"
}
```

When no updates are available (after long-polling timeout elapses):

```json
{
  "updates": [],
  "marker": "<same-marker-or-null>"
}
```

The response is constructed from the `raw_json` column (already valid JSON from
the Max API) -- the receiver stores raw payloads and returns them verbatim.

#### 3.4.3 Marker Strategy

The marker is an opaque string encoding the last-returned row's ID.  Since the
`id` column is a UUID assigned at insertion time and rows are ordered by
`received_at`, the marker value is simply the `id` of the last update in the
batch.

- **On first poll (no marker):** Return the oldest unprocessed updates.
- **With marker:** The marker represents the last update the bot received.
  Since the `GET` handler marks returned updates as processed (see below),
  the next poll simply fetches the next batch of unprocessed updates.
  The marker is passed through but the primary ordering mechanism is the
  `processed = 0 ORDER BY received_at ASC` query.

In practice, the marker serves as a protocol-compatibility token rather than
a strict cursor, because the `GET` handler marks updates as processed on read
(eliminating the need for cursor-based resumption).

#### 3.4.4 Atomic Read-and-Mark

The `GET /updates` handler atomically reads unprocessed updates and marks them
as processed.  This means:

1. Query: `SELECT id, raw_json FROM webhook_updates WHERE processed = 0 ORDER BY received_at ASC LIMIT :limit`
2. If results found: `UPDATE webhook_updates SET processed = 1, processed_at = :now WHERE id IN (:ids)`
3. Return the `raw_json` payloads wrapped in the Max API response format.

The bot does **not** need a separate `markProcessed` call -- the act of polling
marks them.  This is safe because:

- Only one bot process polls at a time (single-process architecture).
- If the bot crashes after receiving the response but before processing the
  updates, those updates are lost -- same behavior as the real Max API where
  passing a `marker` acknowledges prior updates.

#### 3.4.5 Long-Polling Simulation

When no unprocessed updates exist, the handler holds the connection open for
up to `timeout` seconds, re-checking every 0.5 seconds:

```python
async def handleGetUpdates(request: web.Request) -> web.Response:
    """Handle GET /updates -- serve stored webhook updates in Max API format.

    Implements long-polling: if no updates are available, holds the
    connection for up to `timeout` seconds before returning empty.
    Marks returned updates as processed atomically.

    Args:
        request: The incoming aiohttp request.

    Returns:
        JSON response matching Max API /updates format.
    """
    app = request.app

    # Optional: verify shared secret for GET endpoint
    getSecret: str = app.get("getUpdatesSecret", "")
    if getSecret:
        authHeader = request.headers.get("Authorization", "")
        if not hmac.compare_digest(authHeader.encode(), getSecret.encode()):
            return web.json_response({"error": "Forbidden"}, status=403)

    # Parse query params (match Max API behavior)
    limit = max(1, min(1000, int(request.query.get("limit", "100"))))
    timeout = max(0, min(90, int(request.query.get("timeout", "30"))))
    marker = request.query.get("marker")

    database: Database = app["database"]
    POLL_INTERVAL = 0.5  # seconds between re-checks during long-poll

    # Long-polling loop
    elapsed = 0.0
    while True:
        rows = await database.webhookUpdates.getUnprocessedUpdates(limit=limit)

        if rows:
            # Build response
            updates = []
            rowIds: list[str] = []
            lastId: str = ""
            for row in rows:
                updates.append(json.loads(row["raw_json"]))
                rowIds.append(row["id"])
                lastId = row["id"]

            # Mark as processed
            await database.webhookUpdates.markProcessed(rowIds)

            return web.json_response({
                "updates": updates,
                "marker": lastId,
            })

        # No updates -- wait or return empty
        if elapsed >= timeout:
            return web.json_response({
                "updates": [],
                "marker": marker,
            })

        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
```

#### 3.4.6 Security

The `GET /updates` endpoint is the bot's data source -- it must be protected:

- **Default: localhost-only binding.** The receiver listens on `127.0.0.1`
  by default, so only local processes can reach it.
- **Optional shared secret:** If `webhook-receiver.get-updates-secret` is
  configured, the handler checks the `Authorization` header.  The bot passes
  this via the existing `MaxBotClient` `accessToken` parameter (which sets the
  `Authorization` header on every request -- see `lib/max_bot/client.py:223`).
  This means the bot's token is used for local auth, which is fine for localhost.
  For non-localhost deployments, configure a separate secret.

### 3.5 HTTPS / TLS Setup

Max requires the webhook endpoint to use HTTPS on port 443 with a CA-trusted
or Mincifry (Russian government CA) certificate.  Self-signed certificates
are **not accepted**.

**Recommended approach: reverse proxy (nginx/Caddy).**

```
  Internet (port 443, TLS)
       │
       ▼
  ┌──────────────────┐
  │  nginx / Caddy   │    TLS termination, Let's Encrypt auto-renewal
  │  port 443        │
  └────────┬─────────┘
           │ HTTP (plaintext, localhost only)
           ▼
  ┌──────────────────┐
  │ Webhook Receiver │
  │  127.0.0.1:8443  │    (configurable listen host:port)
  └──────────────────┘
```

This is the standard production pattern:

- The receiver itself listens on a local port (e.g., `127.0.0.1:8443`) via
  plain HTTP -- no need for the Python process to handle TLS or run as root.
- nginx/Caddy handles TLS with a real CA certificate (Let's Encrypt has
  automatic renewal).
- The reverse proxy should route `/webhook` to the receiver and block external
  access to `/updates` (only the bot on localhost needs it).
- The configuration only needs `listen_host` and `listen_port` for the receiver.

**Alternative: direct TLS in the receiver.**

For simpler deployments (single server, no nginx), `aiohttp` can serve TLS
directly:

```python
import ssl

sslCtx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
sslCtx.load_cert_chain(certFile, keyFile)
web.run_app(app, host=host, port=port, ssl_context=sslCtx)
```

The configuration would add optional `tls_cert_file` and `tls_key_file` fields.
If both are set, the receiver serves HTTPS directly.  If omitted, it serves
plain HTTP (expecting a reverse proxy).

### 3.6 Entry Point

The receiver is a standalone script, invoked as:

```bash
./venv/bin/python3 -m internal.max_webhook_receiver \
    --config-dir configs/00-defaults \
    --config-dir configs/local
```

It reuses the project's `ConfigManager` to load TOML configuration, then
initializes only the database components it needs (no bot, no LLM, no handlers).

`internal/max_webhook_receiver/__main__.py` skeleton:

```python
"""Entry point for the Max webhook receiver process."""

import argparse
import asyncio
import logging

from aiohttp import web

from internal.config.manager import ConfigManager
from internal.database import Database

from .app import createApp

logger = logging.getLogger(__name__)


def parseArgs() -> argparse.Namespace:
    """Parse command-line arguments for the webhook receiver.

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(description="Max Messenger Webhook Receiver")
    parser.add_argument(
        "--config-dir",
        action="append",
        help="TOML config directory (can be specified multiple times)",
    )
    parser.add_argument(
        "--dotenv-file",
        default=".env",
        help="Path to .env file",
    )
    return parser.parse_args()


def main() -> None:
    """Run the webhook receiver."""
    args = parseArgs()
    configManager = ConfigManager(
        configPath="config.toml",
        configDirs=args.config_dir,
        dotEnvFile=args.dotenv_file,
    )

    webhookConfig = configManager.config.get("webhook-receiver", {})
    host = webhookConfig.get("listen-host", "127.0.0.1")
    port = webhookConfig.get("listen-port", 8443)
    secret = webhookConfig.get("secret", "")
    getUpdatesSecret = webhookConfig.get("get-updates-secret", "")
    webhookPath = webhookConfig.get("webhook-path", "/webhook")

    if not secret:
        logger.error("webhook-receiver.secret is not configured -- exiting")
        raise SystemExit(1)

    database = Database(configManager.getDatabaseConfig())

    app = createApp(
        database=database,
        secret=secret,
        getUpdatesSecret=getUpdatesSecret,
        webhookPath=webhookPath,
    )

    # Optional TLS
    sslCtx = None
    certFile = webhookConfig.get("tls-cert-file")
    keyFile = webhookConfig.get("tls-key-file")
    if certFile and keyFile:
        import ssl
        sslCtx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        sslCtx.load_cert_chain(certFile, keyFile)

    web.run_app(app, host=host, port=port, ssl_context=sslCtx)


if __name__ == "__main__":
    main()
```

### 3.7 Application Factory (`app.py`)

```python
"""Webhook receiver aiohttp application."""

import asyncio
import hmac
import json
import logging
import uuid

from aiohttp import web

from internal.database import Database
from internal.database import utils as dbUtils

logger = logging.getLogger(__name__)

SECRET_HEADER = "X-Max-Bot-Api-Secret"
"""Header name containing the webhook secret from Max."""

CLEANUP_INTERVAL_SECONDS = 300
"""How often to run the cleanup task (5 minutes)."""

CLEANUP_TTL_SECONDS = 3600
"""Delete processed updates older than 1 hour."""


async def handleWebhook(request: web.Request) -> web.Response:
    """Handle incoming webhook POST from Max Messenger.

    Verifies the secret header, parses the JSON body, and stores the
    raw update in the webhook_updates table.

    Args:
        request: The incoming aiohttp request.

    Returns:
        HTTP 200 on success, 403 on bad secret, 400 on bad JSON.
    """
    app = request.app
    expectedSecret: str = app["webhookSecret"]

    # 1. Verify secret
    headerSecret = request.headers.get(SECRET_HEADER, "")
    if not hmac.compare_digest(headerSecret.encode(), expectedSecret.encode()):
        logger.warning("Webhook request with invalid secret from %s", request.remote)
        return web.Response(status=403, text="Forbidden")

    # 2. Parse JSON
    try:
        body = await request.read()
        data = json.loads(body)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Malformed webhook body: %s", e)
        return web.Response(status=400, text="Bad Request")

    # 3. Store to DB
    updateType = data.get("update_type", "unknown")
    rawJson = body.decode("utf-8", errors="replace")

    database: Database = app["database"]
    try:
        await database.webhookUpdates.addUpdate(
            updateId=str(uuid.uuid4()),
            updateType=updateType,
            rawJson=rawJson,
        )
    except Exception as e:
        logger.error("Failed to store webhook update: %s", e)
        # Return 200 to avoid Max retrying -- the event is logged.

    return web.Response(status=200)


async def handleGetUpdates(request: web.Request) -> web.Response:
    """Handle GET /updates -- serve stored webhook updates in Max API format.

    Implements long-polling: if no updates are available, holds the
    connection for up to `timeout` seconds before returning empty.
    Marks returned updates as processed atomically.

    Args:
        request: The incoming aiohttp request.

    Returns:
        JSON response matching Max API /updates format.
    """
    app = request.app

    # Optional: verify shared secret for GET endpoint
    getSecret: str = app.get("getUpdatesSecret", "")
    if getSecret:
        authHeader = request.headers.get("Authorization", "")
        if not hmac.compare_digest(authHeader.encode(), getSecret.encode()):
            return web.json_response({"error": "Forbidden"}, status=403)

    # Parse query params (match Max API clamping)
    try:
        limit = max(1, min(1000, int(request.query.get("limit", "100"))))
    except ValueError:
        limit = 100
    try:
        timeout = max(0, min(90, int(request.query.get("timeout", "30"))))
    except ValueError:
        timeout = 30
    marker = request.query.get("marker")

    database: Database = app["database"]
    pollInterval = 0.5

    elapsed = 0.0
    while True:
        rows = await database.webhookUpdates.getUnprocessedUpdates(limit=limit)

        if rows:
            updates: list[dict] = []
            rowIds: list[str] = []
            lastId: str = ""
            for row in rows:
                updates.append(json.loads(row["raw_json"]))
                rowIds.append(row["id"])
                lastId = row["id"]

            await database.webhookUpdates.markProcessed(rowIds)

            return web.json_response({
                "updates": updates,
                "marker": lastId,
            })

        if elapsed >= timeout:
            return web.json_response({
                "updates": [],
                "marker": marker,
            })

        await asyncio.sleep(pollInterval)
        elapsed += pollInterval


async def cleanupTask(app: web.Application) -> None:
    """Background task to delete old processed webhook updates.

    Runs periodically and removes rows where processed = 1 and
    processed_at is older than CLEANUP_TTL_SECONDS.

    Args:
        app: The aiohttp Application (for database access).

    Returns:
        None
    """
    database: Database = app["database"]
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            await database.webhookUpdates.deleteProcessedOlderThan(
                ttlSeconds=CLEANUP_TTL_SECONDS,
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Cleanup task error: %s", e)


async def startCleanupTask(app: web.Application) -> None:
    """Start the background cleanup task on app startup.

    Args:
        app: The aiohttp Application.

    Returns:
        None
    """
    app["cleanupTask"] = asyncio.create_task(cleanupTask(app))


async def stopCleanupTask(app: web.Application) -> None:
    """Stop the background cleanup task on app shutdown.

    Args:
        app: The aiohttp Application.

    Returns:
        None
    """
    task = app.get("cleanupTask")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def createApp(
    *,
    database: Database,
    secret: str,
    getUpdatesSecret: str = "",
    webhookPath: str = "/webhook",
) -> web.Application:
    """Create and configure the aiohttp web application.

    Args:
        database: Initialized Database instance for storing updates.
        secret: Expected webhook secret for POST /webhook verification.
        getUpdatesSecret: Optional secret for GET /updates verification.
            If empty, no auth check on GET /updates (relies on localhost binding).
        webhookPath: URL path for the webhook endpoint (default /webhook).

    Returns:
        Configured aiohttp Application ready to run.
    """
    app = web.Application()
    app["database"] = database
    app["webhookSecret"] = secret
    app["getUpdatesSecret"] = getUpdatesSecret

    app.router.add_post(webhookPath, handleWebhook)
    app.router.add_get("/updates", handleGetUpdates)

    app.on_startup.append(startCleanupTask)
    app.on_cleanup.append(stopCleanupTask)

    return app
```

### 3.8 Startup & Shutdown

On startup:
1. Load config via `ConfigManager`.
2. Initialize `Database` (runs migrations, including the new
   `webhook_updates` table).
3. Create `aiohttp.web.Application` with both routes and start serving.
4. Background cleanup task starts automatically.

On shutdown (SIGTERM/SIGINT):
1. Cleanup task is cancelled.
2. `aiohttp` handles graceful shutdown of in-flight requests (including any
   long-polling `GET /updates` connections).
3. Close database connections via `database.manager.closeAll()`.

The receiver does **not** register/unregister the webhook with Max -- that is
the bot's responsibility (Part B).

---

## 4. Part B: Bot-Side Changes

### 4.1 URL Override for Polling

The key insight of this architecture: the bot's `MaxBotClient._pollingLoop()`
already implements all the logic needed to poll for updates -- marker-based
pagination, error handling, retry with backoff, cancellation.  The only change
is **where** `GET /updates` points.

| Mode | `GET /updates` target | Code path |
|------|----------------------|-----------|
| Long-polling (current, default) | `https://platform-api2.max.ru/updates` | `_pollingLoop()` unchanged |
| Webhook (new) | `http://127.0.0.1:8443/updates` | `_pollingLoop()` unchanged, different `basePollingUrl` |

No `_runLocalDbPolling()` method.  No `parseUpdateFromDict()` extraction.  No
new polling logic at all.  The bot's entire deserialization pipeline
(`getUpdates()` -> `UpdateList.from_dict()` with all 16 update types) works
unchanged because the receiver returns JSON identical to the real Max API.

### 4.2 Changes to `MaxBotClient`

File: `lib/max_bot/client.py`

**Add `basePollingUrl` parameter to `__init__()`:**

```python
def __init__(
    self,
    accessToken: str,
    baseUrl: str = API_BASE_URL,
    timeout: int = DEFAULT_TIMEOUT,
    maxRetries: int = MAX_RETRIES,
    retryBackoffFactor: float = RETRY_BACKOFF_FACTOR,
    proxyConfig: Optional[ProxyConfig] = None,
    caBundlePath: Optional[str] = None,
    basePollingUrl: Optional[str] = None,
) -> None:
```

**Add to `__slots__`:**

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
    "_sslContext",
    "_basePollingUrl",
)
```

**Store in `__init__` body:**

```python
self._basePollingUrl: Optional[str] = basePollingUrl.rstrip("/") if basePollingUrl else None
```

**Modify `_buildUrl()` -- no change needed.**  Instead, override the URL only
in `getUpdates()`:

```python
async def getUpdates(
    self,
    lastEventId: Optional[int] = None,
    limit: int = 100,
    timeout: int = 30,
    types: Optional[List[str]] = None,
) -> UpdateList:
    # ... existing docstring and param construction ...

    params: Dict[str, Any] = {
        "limit": max(1, min(1000, limit)),
        "timeout": max(0, min(90, timeout)),
    }

    if lastEventId is not None:
        params["marker"] = lastEventId

    if types is not None:
        params["types"] = ",".join(types)

    # Use local receiver URL if configured, otherwise real API
    if self._basePollingUrl:
        response = await self._makeLocalRequest("/updates", params=params)
    else:
        response = await self.get("/updates", params=params)

    if EXTENDED_DEBUG and response.get("updates", []):
        logger.debug(f"Received updates: {utils.jsonDumps(response, indent=2)}")
    return UpdateList.from_dict(response)
```

**Note:** The existing `getUpdates(lastEventId: Optional[int])` parameter type
is `int` because the real Max API uses integer markers. The webhook receiver
uses UUID string markers. At runtime this works (Python doesn't enforce types,
and httpx serializes the value correctly for query parameters). The
implementer may consider widening the type to `Optional[Union[int, str]]` for
honesty, but this is not required for correctness.

**New private method `_makeLocalRequest()`** for the local receiver:

```python
async def _makeLocalRequest(
    self,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make a GET request to the local webhook receiver.

    Uses a separate httpx client configured for the local receiver URL,
    bypassing the main API client's base URL, proxy, and TLS settings.

    Args:
        endpoint: Endpoint path (e.g., "/updates").
        params: Query parameters.

    Returns:
        Parsed JSON response data.

    Raises:
        NetworkError: If the request fails.
    """
    url = self._basePollingUrl + "/" + endpoint.lstrip("/")
    timeout = httpx.Timeout(self.timeout + 10)  # extra margin over long-poll timeout

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Pass the access token in Authorization header for optional auth
            headers = {"Authorization": self.accessToken}
            response = await client.get(url, params=params, headers=headers)

            if response.status_code == 200:
                return response.json()

            raise NetworkError(
                f"Local receiver returned {response.status_code}: {response.text}"
            )
    # Safety net: this fires only if the receiver crashes or hangs mid-poll.
    # The normal empty-poll path returns HTTP 200 with {"updates":[],"marker":"..."}
    # before the client's timeout expires (client timeout is self.timeout+10=40s,
    # receiver's max long-poll hold is 30s by default).
    except httpx.ReadTimeout:
        return {"updates": [], "marker": None}
    except httpx.RequestError as e:
        raise NetworkError(f"Failed to reach local receiver at {url}: {e}")
```

**Why a separate method instead of just changing `self.baseUrl`?**

The `self.baseUrl` is used by `_getHttpClient()` (line 210) as `base_url` for
the httpx client, and by `_buildUrl()` (line 247).  If we changed `baseUrl`,
ALL API calls (including `POST /subscriptions`, `GET /me`, `POST /messages`,
etc.) would be redirected to the local receiver -- which only understands
`/updates` and `/webhook`.  We need to redirect **only** the `/updates`
polling traffic while keeping all other API calls pointed at the real Max API.

A separate method also avoids the retry logic and proxy configuration that
the main `_makeRequest()` applies -- the local receiver doesn't need exponential
backoff or SOCKS5 proxying.

### 4.3 Webhook Subscription Lifecycle

The bot manages the webhook registration with the real Max API.  This is
**optional** and controlled by `webhook-receiver.register-webhook` (default
`true`).

On bot startup (when `webhook-receiver.enabled = true` AND
`webhook-receiver.register-webhook = true`):

```python
# In MaxBotApplication._runPolling(), after creating MaxBotClient:
webhookConfig = self.configManager.config.get("webhook-receiver", {})

if webhookConfig.get("register-webhook", True):
    webhookUrl = webhookConfig.get("webhook-url", "")
    webhookSecret = webhookConfig.get("secret", "")
    webhookTypes = webhookConfig.get("webhook-update-types", None) or None

    if not webhookUrl:
        raise RuntimeError(
            "webhook-receiver.webhook-url is required when register-webhook is true"
        )

    await self.maxBot.setWebhook(
        url=webhookUrl,
        types=webhookTypes,
        secret=webhookSecret,
    )
    logger.info("Webhook registered with Max: %s", webhookUrl)
```

On bot shutdown (when `webhook-receiver.enabled = true` AND
`webhook-receiver.register-webhook = true`):

```python
# In MaxBotApplication.postStop():
if self._webhookMode and self.maxBot is not None:
    webhookConfig = self.configManager.config.get("webhook-receiver", {})
    if webhookConfig.get("register-webhook", True):
        try:
            webhookUrl = webhookConfig.get("webhook-url", "")
            if webhookUrl:
                await self.maxBot.deleteWebhook(webhookUrl)
                logger.info("Webhook unregistered from Max")
        except Exception as e:
            logger.warning("Failed to unregister webhook: %s", e)
```

The existing `MaxBotClient.setWebhook()` (`lib/max_bot/client.py:1352-1388`)
and `MaxBotClient.deleteWebhook()` (`lib/max_bot/client.py:1390`) are already
implemented and ready to use.

**When `register-webhook = false`:** The bot assumes the webhook is managed
externally (e.g., registered manually via the Max API, or managed by a
deployment script).  Useful for testing, shared environments, or when the
webhook is persistent and doesn't need re-registration.

### 4.4 Changes to `MaxBotApplication`

File: `internal/bot/max/application.py`

Summary of modifications:

| Location | Change |
|----------|--------|
| Class attributes | Add `self._webhookMode: bool = False` |
| `_runPolling()` (line 264) | After creating `MaxBotClient`, read `webhook-receiver` config.  If enabled: pass `basePollingUrl` to `MaxBotClient.__init__()`, optionally register webhook, set `self._webhookMode = True`.  The existing `startPolling()` call remains identical. |
| `postStop()` (line 101) | Before existing cleanup: if `self._webhookMode`, call `deleteWebhook()`. |

**Modified `_runPolling()` sketch:**

```python
async def _runPolling(self) -> None:
    """Run the Max Messenger bot polling loop.

    Reads webhook-receiver config.  If enabled, configures the MaxBotClient
    to poll the local webhook receiver instead of the real Max API, and
    optionally registers the webhook subscription.  Otherwise, uses the
    default long-polling path unchanged.

    Returns:
        None
    """
    # --- Proxy support ---
    botConfig = self.configManager.getBotConfig()
    proxyConfig = ProxyService.getInstance().resolveProxy(botConfig, "max-bot")
    maskedUrl = proxyConfig.getProxyURL(maskPassword=True)
    if maskedUrl:
        logger.info("Proxy enabled for Max bot: %s", maskedUrl)

    # --- Webhook receiver config ---
    webhookConfig = self.configManager.config.get("webhook-receiver", {})
    self._webhookMode = webhookConfig.get("enabled", False)
    basePollingUrl: Optional[str] = None

    if self._webhookMode:
        basePollingUrl = webhookConfig.get("base-polling-url", "http://127.0.0.1:8443")
        logger.info("Webhook mode enabled, polling receiver at %s", basePollingUrl)

    # --- TLS: trust Минцифры CA for platform-api2.max.ru ---
    self.maxBot = libMax.MaxBotClient(
        self.botToken,
        proxyConfig=proxyConfig,
        caBundlePath=botConfig.get("max-ca-bundle", ""),
        basePollingUrl=basePollingUrl,
    )

    try:
        botInfo = await self.maxBot.getMyInfo()
        logger.debug(botInfo)

        await self.postInit()

        # Register webhook if configured
        if self._webhookMode and webhookConfig.get("register-webhook", True):
            webhookUrl = webhookConfig.get("webhook-url", "")
            webhookSecret = webhookConfig.get("secret", "")
            webhookTypes = webhookConfig.get("webhook-update-types", None) or None

            if not webhookUrl:
                raise RuntimeError(
                    "webhook-receiver.webhook-url is required when register-webhook is true"
                )

            await self.maxBot.setWebhook(
                url=webhookUrl,
                types=webhookTypes,
                secret=webhookSecret,
            )
            logger.info("Webhook registered with Max: %s", webhookUrl)

        logger.info("Start MAX polling....")
        await self.maxBot.startPolling(
            handler=self.maxHandler,
            types=None,
            timeout=30,
            errorHandler=self.maxExceptionHandler,
        )

        if self.maxBot._pollingTask is not None:
            await self.maxBot._pollingTask
        logger.info("After polling...")
    finally:
        logger.info("Work is done, exiting...")
        await self.postStop()
        await self.maxBot.aclose()
```

**Note:** The `startPolling()` call and its handler/types/timeout/errorHandler
arguments are **identical** in both modes.  The only difference is the
`basePollingUrl` passed to the `MaxBotClient` constructor, which causes
`getUpdates()` to hit the local receiver instead of `platform-api2.max.ru`.

**Fallback:** If `webhook-receiver.enabled = false` (the default), the bot
uses long-polling exactly as it does today.  Zero behavioral change for
existing deployments.

---

## 5. Part C: Database Schema

### 5.1 New Table: `webhook_updates`

```sql
CREATE TABLE IF NOT EXISTS webhook_updates (
    id            TEXT      PRIMARY KEY NOT NULL,
    received_at   TIMESTAMP NOT NULL,
    update_type   TEXT      NOT NULL,
    raw_json      TEXT      NOT NULL,
    processed     INTEGER   NOT NULL DEFAULT 0,
    processed_at  TIMESTAMP
)
```

**Notes on portability (per `docs/sql-portability-guide.md` and `AGENTS.md`):**

- `id` is `TEXT PRIMARY KEY` -- application-generated UUID, no `AUTOINCREMENT`.
- No `DEFAULT CURRENT_TIMESTAMP` -- `received_at` is set by application code
  via `dbUtils.getCurrentTimestamp()`.
- `processed` is `INTEGER NOT NULL DEFAULT 0` -- booleans stored as 0/1.
  The `DEFAULT 0` here is a plain integer default, not a timestamp, so it is
  portable.
- `:named` placeholders throughout.
- Uses `BaseSQLProvider` for all operations.

**Index for polling queries:**

```sql
CREATE INDEX IF NOT EXISTS idx_webhook_updates_unprocessed
ON webhook_updates (processed, received_at)
```

This index accelerates the primary query pattern:
`WHERE processed = 0 ORDER BY received_at ASC LIMIT :limit`.

### 5.2 Migration

Next migration number: **019** (the latest existing is `migration_018_message_embeddings_index.py`).

File: `internal/database/migrations/versions/migration_019_add_webhook_updates_table.py`

```python
"""Migration: add webhook_updates table - v019."""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration019AddWebhookUpdatesTable(BaseMigration):
    """Add webhook_updates table for Max webhook event storage.

    Stores raw update JSON from the webhook receiver process. The
    local GET /updates endpoint reads from this table and returns
    updates in Max API format to the bot's polling loop.

    Attributes:
        version: Migration version number (19).
        description: Human-readable description.
    """

    version: int = 19
    description: str = "Add webhook_updates table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create webhook_updates table and index.

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
                    CREATE TABLE IF NOT EXISTS webhook_updates (
                        id            TEXT      PRIMARY KEY NOT NULL,
                        received_at   TIMESTAMP NOT NULL,
                        update_type   TEXT      NOT NULL,
                        raw_json      TEXT      NOT NULL,
                        processed     INTEGER   NOT NULL DEFAULT 0,
                        processed_at  TIMESTAMP
                    )
                """),
                ParametrizedQuery("""
                    CREATE INDEX IF NOT EXISTS idx_webhook_updates_unprocessed
                    ON webhook_updates (processed, received_at)
                """),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop webhook_updates table and index.

        Args:
            sqlProvider: SQL provider abstraction.

        Returns:
            None
        """
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("DROP INDEX IF EXISTS idx_webhook_updates_unprocessed"),
                ParametrizedQuery("DROP TABLE IF EXISTS webhook_updates"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class.
    """
    return Migration019AddWebhookUpdatesTable
```

### 5.3 Repository: `WebhookUpdatesRepository`

File: `internal/database/repositories/webhook_updates.py`

Define `WebhookUpdatesRow` in `internal/database/models.py` (following the
pattern of `DelayedTaskDict` and other row TypedDicts) with fields: `id: str`,
`received_at: str`, `update_type: str`, `raw_json: str`, `processed: int`,
`processed_at: str`. Import it in the repository via
`from ..models import WebhookUpdatesRow`.

```python
"""Repository for webhook update storage and retrieval."""

import logging
from typing import List

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import WebhookUpdatesRow
from .base import BaseRepository

logger = logging.getLogger(__name__)


class WebhookUpdatesRepository(BaseRepository):
    """Repository for managing webhook update events in the database.

    Provides methods to store incoming webhook updates, retrieve unprocessed
    updates for the bot to consume, mark updates as processed, and clean up
    old processed events.

    Attributes:
        manager: DatabaseManager instance for database operations.
    """

    __slots__ = ()

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the webhook updates repository.

        Args:
            manager: DatabaseManager instance for database access.

        Returns:
            None
        """
        super().__init__(manager)

    async def addUpdate(
        self,
        updateId: str,
        updateType: str,
        rawJson: str,
    ) -> bool:
        """Store a raw webhook update in the database.

        Args:
            updateId: Unique identifier (UUID) for this update.
            updateType: The update_type string from the Max API payload.
            rawJson: Full JSON body as a string.

        Returns:
            True if stored successfully, False on error.
        """
        try:
            sqlProvider = await self.manager.getProvider(readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO webhook_updates
                    (id, received_at, update_type, raw_json, processed)
                VALUES
                    (:id, :receivedAt, :updateType, :rawJson, 0)
                """,
                {
                    "id": updateId,
                    "receivedAt": dbUtils.getCurrentTimestamp(),
                    "updateType": updateType,
                    "rawJson": rawJson,
                },
            )
            return True
        except Exception as e:
            logger.error("Failed to store webhook update: %s", e)
            return False

    async def getUnprocessedUpdates(
        self,
        limit: int = 100,
    ) -> List[WebhookUpdatesRow]:
        """Retrieve unprocessed webhook updates ordered by arrival time.

        Args:
            limit: Maximum number of updates to return.

        Returns:
            List of WebhookUpdatesRow dicts with keys: id, received_at,
            update_type, raw_json.
        """
        sqlProvider = await self.manager.getProvider(readonly=True)
        query = """
            SELECT id, received_at, update_type, raw_json
            FROM webhook_updates
            WHERE processed = 0
            ORDER BY received_at ASC
        """
        query = sqlProvider.applyPagination(query, limit=limit, offset=0)
        result = await sqlProvider.executeFetchAll(query)
        return [dbUtils.sqlToTypedDict(row, WebhookUpdatesRow) for row in result] if result else []

    async def markProcessed(self, updateIds: List[str]) -> None:
        """Mark a batch of updates as processed.

        Args:
            updateIds: List of update IDs to mark as processed.

        Returns:
            None
        """
        if not updateIds:
            return

        sqlProvider = await self.manager.getProvider(readonly=False)
        now = dbUtils.getCurrentTimestamp()

        for updateId in updateIds:
            await sqlProvider.execute(
                """
                UPDATE webhook_updates
                SET processed = 1, processed_at = :processedAt
                WHERE id = :id
                """,
                {"id": updateId, "processedAt": now},
            )

    async def deleteProcessedOlderThan(self, ttlSeconds: int = 3600) -> int:
        """Delete processed updates older than the specified TTL.

        Uses dbUtils.getCurrentTimestamp() for portable timestamp arithmetic.

        Args:
            ttlSeconds: Age threshold in seconds. Processed updates with
                processed_at older than now - ttlSeconds are deleted.

        Returns:
            Number of rows deleted (0 if provider doesn't report it).
        """
        sqlProvider = await self.manager.getProvider(readonly=False)
        cutoff = dbUtils.getTimestampMinusSeconds(ttlSeconds)
        await sqlProvider.execute(
            """
            DELETE FROM webhook_updates
            WHERE processed = 1 AND processed_at < :cutoff
            """,
            {"cutoff": cutoff},
        )
        return 0  # Row count not easily available across providers
```

**Note on `deleteProcessedOlderThan`:** The original plan used
`datetime.datetime.now(datetime.timezone.utc)` directly, which bypasses the
project's timestamp utilities.  The revised version uses
`dbUtils.getTimestampMinusSeconds()` (or equivalent -- if this helper doesn't
exist, compute via `dbUtils.getCurrentTimestamp()` minus a `timedelta` and
format consistently).  The implementer should check `internal/database/utils.py`
for available timestamp helpers and use them.

### 5.4 Wiring the Repository into `Database`

In `internal/database/database.py`, five changes (following the pattern of
existing repositories like `delayedTasks`, `divinations`, `cache`):

1. **Import:** Add `WebhookUpdatesRepository` to the imports from
   `.repositories`.
2. **`__slots__`:** Add `"webhookUpdates"` to the tuple.
3. **Type annotation with docstring:** Add the class-level attribute:
   ```python
   webhookUpdates: WebhookUpdatesRepository
   """Repository for webhook update event storage and retrieval."""
   ```
4. **Docstring `Attributes:` block:** Add the entry:
   ```
   webhookUpdates: Repository for webhook update event storage and retrieval.
   ```
5. **`__init__()` body:** Add:
   ```python
   self.webhookUpdates = WebhookUpdatesRepository(self.manager)
   ```

Also in `internal/database/repositories/__init__.py`:

6. **Import:** Add `from .webhook_updates import WebhookUpdatesRepository`
7. **`__all__`:** Add `"WebhookUpdatesRepository"` to the list.

---

## 6. Part D: Configuration

### 6.1 New TOML Config File

File: `configs/00-defaults/webhook-receiver.toml`

```toml
# Max Messenger webhook receiver configuration.
# Used by both the standalone webhook receiver process and the bot process.
# The receiver stores incoming webhook events and serves them to the bot
# via a local GET /updates endpoint that speaks the Max API protocol.

[webhook-receiver]
# Master switch.  When true, the bot polls the local webhook receiver's
# GET /updates endpoint instead of long-polling the real Max API.
# The webhook receiver process always runs regardless of this flag.
enabled = false

# --- Webhook subscription (bot manages with Max API) ---

# Whether the bot should register/unregister the webhook with Max on
# startup/shutdown.  Set to false if the webhook is managed externally
# (e.g., registered manually or by a deployment script).
register-webhook = true

# Public HTTPS URL that Max will POST updates to.
# This must be a valid HTTPS URL on port 443 with a CA-trusted certificate.
# Required when register-webhook = true.
# Example: "https://bot.example.com/webhook"
webhook-url = ""

# Shared secret for verifying webhook requests from Max.
# Set via environment variable -- never commit the actual value.
# Max sends this in the X-Max-Bot-Api-Secret header on every webhook POST.
secret = "${MAX_WEBHOOK_SECRET}"

# List of update types the bot wants to receive via webhook.
# Empty list = all types (default).
# Example: ["message_created", "message_callback"]
webhook-update-types = []

# --- Polling (bot polls the receiver, not the real Max API) ---

# URL of the webhook receiver's local GET /updates endpoint.
# The bot polls this instead of platform-api2.max.ru when enabled = true.
base-polling-url = "http://127.0.0.1:8443"

# --- Receiver process settings (only used by the receiver, not the bot) ---

# Listen address for the webhook receiver HTTP server.
# Default: 127.0.0.1 (localhost only -- use a reverse proxy for external TLS).
listen-host = "127.0.0.1"

# Listen port for the webhook receiver HTTP server.
listen-port = 8443

# URL path for the webhook POST endpoint from Max.
# Change this if your reverse proxy routes to a different path.
webhook-path = "/webhook"

# Optional secret for the GET /updates endpoint.
# If set, the receiver checks the Authorization header on GET /updates.
# If empty (default), no auth check -- relies on localhost binding for security.
get-updates-secret = ""

# Optional: path to TLS certificate and key for direct HTTPS serving.
# If both are set, the receiver serves HTTPS directly (no reverse proxy needed).
# If omitted, the receiver serves plain HTTP (reverse proxy expected).
# tls-cert-file = "/path/to/cert.pem"
# tls-key-file = "/path/to/key.pem"
```

### 6.2 Environment Variables

Add to `.env.example` (or document in the plan):

```bash
# Max Webhook Receiver
MAX_WEBHOOK_SECRET="your-webhook-secret-here"
```

### 6.3 Config Keys by Consumer

| Config key | Used by | Purpose |
|------------|---------|---------|
| `enabled` | Bot | Master switch: poll receiver instead of Max API |
| `register-webhook` | Bot | Whether to call `POST /subscriptions` on startup |
| `webhook-url` | Bot | Public URL passed to `setWebhook()` |
| `secret` | Bot + Receiver | Bot passes to `setWebhook()`; receiver verifies POST |
| `webhook-update-types` | Bot | Passed to `setWebhook()` types parameter |
| `base-polling-url` | Bot | Where to `GET /updates` from |
| `listen-host` | Receiver | Bind address |
| `listen-port` | Receiver | Bind port |
| `webhook-path` | Receiver | Path for POST endpoint |
| `get-updates-secret` | Receiver | Optional auth for GET endpoint |
| `tls-cert-file` | Receiver | Optional TLS |
| `tls-key-file` | Receiver | Optional TLS |

---

## 7. Implementation Sequence

Ordered steps for a `software-developer` agent.  Each step is independently
testable.

### Step 1: Add `aiohttp` to Direct Dependencies

**Files to modify:**

| File | Action |
|------|--------|
| `requirements.direct.txt` | Add `aiohttp==3.14.1` under `# Runtime` section |

**Verification:** `make install` succeeds, `aiohttp` version unchanged in
`requirements.txt`.

### Step 2: Database Migration + Repository

**Files to create/modify:**

| File | Action |
|------|--------|
| `internal/database/migrations/versions/migration_019_add_webhook_updates_table.py` | Create (migration) |
| `internal/database/repositories/webhook_updates.py` | Create (repository with `WebhookUpdatesRow` TypedDict) |
| `internal/database/repositories/__init__.py` | Add `WebhookUpdatesRepository` to imports and `__all__` |
| `internal/database/database.py` | Add `webhookUpdates` slot, type annotation, docstring entry, and init |

**Verification:** `make format lint && make test`

### Step 3: Configuration

**Files to create:**

| File | Action |
|------|--------|
| `configs/00-defaults/webhook-receiver.toml` | Create (TOML config) |

**Verification:** Run `./venv/bin/python3 main.py --print-config --config-dir configs/00-defaults`
and verify `webhook-receiver` section appears with defaults.

### Step 4: Webhook Receiver Application

**Files to create:**

| File | Action |
|------|--------|
| `internal/max_webhook_receiver/__init__.py` | Create (package init with docstring) |
| `internal/max_webhook_receiver/__main__.py` | Create (entry point) |
| `internal/max_webhook_receiver/app.py` | Create (aiohttp app with `POST /webhook` + `GET /updates` handlers + cleanup task) |

**Verification:** `make format lint && make test`.  Manual: start the receiver
and test both endpoints:

```bash
# POST a test update
curl -X POST http://127.0.0.1:8443/webhook \
  -H "X-Max-Bot-Api-Secret: test-secret" \
  -H "Content-Type: application/json" \
  -d '{"update_type": "message_created", "timestamp": 123}'

# GET updates (should return the posted update)
curl "http://127.0.0.1:8443/updates?timeout=1&limit=10"
```

### Step 5: Bot-Side Changes

**Files to modify:**

| File | Action |
|------|--------|
| `lib/max_bot/client.py` | Add `_basePollingUrl` to `__slots__`, `basePollingUrl` param to `__init__()`, add `_makeLocalRequest()` method, modify `getUpdates()` to branch on `_basePollingUrl` |
| `internal/bot/max/application.py` | Add `_webhookMode` attribute, modify `_runPolling()` to read webhook config and pass `basePollingUrl`, modify `postStop()` to unregister webhook |

**Verification:** `make format lint && make test`.

### Step 6: Tests

**Files to create:**

| File | Action |
|------|--------|
| `tests/database/repositories/test_webhook_updates.py` | Repository CRUD tests |
| `tests/max_webhook_receiver/test_app.py` | Receiver endpoint tests (POST + GET) |
| `tests/lib/max_bot/test_client_webhook.py` | `MaxBotClient` with `basePollingUrl` tests |
| `tests/bot/max/test_webhook_mode.py` | `MaxBotApplication` webhook config gating tests |

**Verification:** `make test`

### Step 7: Documentation Sync

**Files to update:**

See [Documentation Impact](#12-documentation-impact).  Load the
`update-project-docs` skill.

---

## 8. Testing Strategy

### 8.1 Repository Tests

Location: `tests/database/repositories/test_webhook_updates.py`

Test with a real in-memory SQLite database (same pattern as existing repository
tests).  Use the `testDatabase` fixture from `tests/conftest.py`.

```python
class TestWebhookUpdatesRepository:
    """Tests for WebhookUpdatesRepository."""

    async def test_addUpdate_storesEvent(self, testDatabase: Database) -> None:
        """Verify addUpdate stores a webhook event."""
        result = await testDatabase.webhookUpdates.addUpdate(
            updateId="test-uuid-1",
            updateType="message_created",
            rawJson='{"update_type": "message_created", "timestamp": 123}',
        )
        assert result is True

    async def test_getUnprocessedUpdates_returnsUnprocessed(
        self, testDatabase: Database
    ) -> None:
        """Verify only unprocessed updates are returned, ordered by time."""
        await testDatabase.webhookUpdates.addUpdate(
            updateId="id-1", updateType="message_created", rawJson='{"update_type": "message_created"}',
        )
        await testDatabase.webhookUpdates.addUpdate(
            updateId="id-2", updateType="message_callback", rawJson='{"update_type": "message_callback"}',
        )
        rows = await testDatabase.webhookUpdates.getUnprocessedUpdates(limit=10)
        assert len(rows) == 2
        assert rows[0]["id"] == "id-1"  # ordered by received_at

    async def test_getUnprocessedUpdates_returnsTypedDict(
        self, testDatabase: Database
    ) -> None:
        """Verify return type is WebhookUpdatesRow, not raw dict."""
        await testDatabase.webhookUpdates.addUpdate(
            updateId="id-1", updateType="message_created", rawJson="{}",
        )
        rows = await testDatabase.webhookUpdates.getUnprocessedUpdates(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert "id" in row
        assert "raw_json" in row

    async def test_markProcessed_marksCorrectRows(
        self, testDatabase: Database
    ) -> None:
        """Verify markProcessed flags the right updates."""
        await testDatabase.webhookUpdates.addUpdate(
            updateId="id-1", updateType="message_created", rawJson="{}",
        )
        await testDatabase.webhookUpdates.markProcessed(["id-1"])
        rows = await testDatabase.webhookUpdates.getUnprocessedUpdates()
        assert len(rows) == 0

    async def test_markProcessed_emptyList_isNoop(
        self, testDatabase: Database
    ) -> None:
        """Verify markProcessed with empty list does nothing."""
        await testDatabase.webhookUpdates.markProcessed([])
        # Should not raise

    async def test_deleteProcessedOlderThan_removesOldEvents(
        self, testDatabase: Database
    ) -> None:
        """Verify cleanup removes old processed events."""
        # Insert, mark processed, adjust timestamps, verify deletion
        ...
```

### 8.2 Webhook Receiver Tests

Location: `tests/max_webhook_receiver/test_app.py`

Use `aiohttp.test_utils.TestClient` to test both handlers without a real
network:

```python
from aiohttp.test_utils import TestClient, TestServer

class TestWebhookPostHandler:
    """Tests for the POST /webhook endpoint."""

    async def test_validRequest_returns200(self) -> None:
        """POST with correct secret and valid JSON returns 200."""
        ...

    async def test_invalidSecret_returns403(self) -> None:
        """POST with wrong secret returns 403."""
        ...

    async def test_malformedJson_returns400(self) -> None:
        """POST with unparseable body returns 400."""
        ...

    async def test_missingSecretHeader_returns403(self) -> None:
        """POST without X-Max-Bot-Api-Secret returns 403."""
        ...

    async def test_validRequest_storesInDb(self) -> None:
        """POST with valid payload is stored in webhook_updates."""
        ...


class TestGetUpdatesHandler:
    """Tests for the GET /updates endpoint."""

    async def test_returnsUnprocessedUpdates(self) -> None:
        """GET /updates returns stored updates in Max API format."""
        ...

    async def test_marksReturnedUpdatesAsProcessed(self) -> None:
        """Updates returned by GET /updates are marked processed."""
        ...

    async def test_subsequentPoll_returnsNewUpdatesOnly(self) -> None:
        """Second GET /updates returns only new (unprocessed) updates."""
        ...

    async def test_emptyDb_returnsEmptyList(self) -> None:
        """GET /updates on empty DB returns {"updates": [], "marker": null}."""
        ...

    async def test_responseFormat_matchesMaxApi(self) -> None:
        """Response JSON matches Max API /updates format exactly."""
        # Store a raw update, retrieve via GET, verify structure
        ...

    async def test_longPoll_waitsBeforeEmpty(self) -> None:
        """GET /updates with timeout waits before returning empty."""
        # Use timeout=1 to keep test fast
        ...

    async def test_limitParam_respectsLimit(self) -> None:
        """GET /updates respects the limit parameter."""
        ...

    async def test_markerInResponse_isLastUpdateId(self) -> None:
        """The marker in the response is the ID of the last returned update."""
        ...

    async def test_optionalAuth_rejects_badSecret(self) -> None:
        """When get-updates-secret is configured, bad auth returns 403."""
        ...
```

### 8.3 MaxBotClient Polling URL Tests

Location: `tests/lib/max_bot/test_client_webhook.py`

Test that `MaxBotClient` routes `/updates` to the local receiver when
`basePollingUrl` is set, while all other API calls still go to the real
base URL:

```python
class TestMaxBotClientBasePollingUrl:
    """Tests for MaxBotClient with basePollingUrl override."""

    async def test_noBasePollingUrl_usesDefaultApi(self) -> None:
        """Without basePollingUrl, getUpdates hits the real API URL."""
        ...

    async def test_withBasePollingUrl_pollsLocalReceiver(self) -> None:
        """With basePollingUrl, getUpdates hits the local receiver."""
        # Mock httpx to verify the request URL
        ...

    async def test_withBasePollingUrl_otherCallsUnchanged(self) -> None:
        """With basePollingUrl, non-polling calls still use real API."""
        # Verify setWebhook, getMyInfo etc. still use API_BASE_URL
        ...
```

### 8.4 Bot-Side Config Gating Tests

Location: `tests/bot/max/test_webhook_mode.py`

Mock MaxBotClient and verify:

- When `webhook-receiver.enabled = false`, `MaxBotClient` is constructed
  without `basePollingUrl`.
- When `webhook-receiver.enabled = true`, `MaxBotClient` is constructed with
  `basePollingUrl` from config.
- When `register-webhook = true`, `setWebhook()` is called on startup and
  `deleteWebhook()` on shutdown.
- When `register-webhook = false`, neither is called.

### 8.5 Integration Test (Optional)

An end-to-end test that:
1. Starts the webhook receiver in-process (aiohttp test server).
2. POSTs a simulated Max update to `POST /webhook`.
3. Creates a `MaxBotClient` with `basePollingUrl` pointing to the test server.
4. Calls `getUpdates()` and verifies it returns the correct `Update` subclass.
5. Calls `getUpdates()` again and verifies the update is not re-returned.

This validates the full pipeline: Max POST -> SQLite -> GET /updates ->
`UpdateList.from_dict()` -> correct `Update` type.

### 8.6 No Real Max Token Needed

All tests use mock data.  The webhook receiver doesn't call the Max API -- it
only receives POSTs and serves GETs.  The bot's `setWebhook()` /
`deleteWebhook()` calls can be mocked via the `mockBot` fixture or by
patching `MaxBotClient`.

---

## 9. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| **SQLite concurrent access (two processes).** WAL mode supports one writer + many readers, but two writers cause `SQLITE_BUSY`. The receiver writes (POST handler); the receiver also writes (GET handler marks processed); the bot only reads via HTTP. | Medium | WAL mode + `timeout=30` in the SQLite provider config already handle contention. The receiver is single-process, so its POST and GET handlers never write simultaneously (async, not threaded). If contention appears with background cleanup, increase timeout or serialize writes. |
| **Webhook receiver goes down.** Max retries for 8 hours, then auto-unsubscribes. | Medium | Monitor receiver uptime. If auto-unsubscribed, the bot must re-register on next startup. Add a periodic health check that calls `getWebhookInfo()` and re-registers if no active subscription (future enhancement). |
| **Receiver's GET /updates goes down.** Bot's polling loop hits `NetworkError`. | Medium | The existing `_pollingLoop()` already handles errors with retry + backoff (5s sleep at `client.py:1348-1349`). The bot keeps retrying until the receiver comes back. |
| **Database grows unbounded.** If cleanup fails or the GET handler doesn't mark properly. | Low | Background cleanup task in the receiver deletes old processed rows every 5 minutes. Max's 8-hour retry window bounds the queue to ~few hundred KB at most. |
| **Event ordering.** Updates are ordered by `received_at` (insertion time), not by Max's `timestamp`. | Low | The receiver processes sequentially; `received_at` reflects arrival order. Max sends events in order. If the receiver is multi-worker (future), a `sequence_number` column would be needed -- not relevant for single-process aiohttp. |
| **Bot and receiver use different DB schema versions.** If only one process is restarted after a migration. | Medium | Both processes run migrations on startup. After deploying a new version, restart both processes. Document this in the deployment guide. |
| **Partial writes on crash.** Receiver crashes mid-INSERT. | Low | SQLite transactions are atomic. The INSERT either commits or doesn't. No partial data. |
| **Max delivers duplicate events.** Network issues cause Max to retry even after 200. | Low | The UUID primary key prevents true duplicates (INSERT would fail). If Max sends the same *logical* event with different bodies, the bot processes both -- acceptable since handler logic is idempotent for most update types. |
| **`_makeLocalRequest()` creates a new httpx client per call.** | Low | This is a localhost request with minimal overhead. If profiling shows this matters, the method can be refactored to reuse a cached client. The simplicity of a fresh client per call avoids connection lifecycle bugs. |
| **Response format mismatch.** If the receiver's JSON doesn't match `UpdateList.from_dict()` expectations. | Medium | The integration test (8.5) validates this end-to-end. The receiver returns raw `raw_json` from Max (stored verbatim), so format is preserved. The wrapping `{"updates": [...], "marker": "..."}` must match -- tested explicitly. |

---

## 10. Resolved Decisions

These items were open questions in the previous version of this plan.  All are
now decided:

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Return 200 or 500 on DB write failure? | **200** | Log the error, don't trigger Max retry. DB write failures are extremely rare with SQLite. |
| 2 | Should the bot remove the webhook on shutdown? | **Yes, but configurable** | `register-webhook = true` (default): unregister on graceful shutdown. `register-webhook = false`: bot doesn't touch webhook lifecycle. |
| 3 | Should `aiohttp` be added to `requirements.direct.txt`? | **Yes** | Add `aiohttp==3.14.1` under `# Runtime`. The receiver imports it directly -- it must be an explicit dependency. |
| 4 | Webhook path: fixed or configurable? | **Configurable** | `webhook-receiver.webhook-path` with default `/webhook`. |
| 5 | Should the receiver validate JSON as a valid Max Update? | **No** | Raw storage. Return 200 fast. Bot validates during processing via `UpdateList.from_dict()`. |
| 6 | Support both modes indefinitely or deprecate long-polling? | **Both indefinitely** | Long-polling is useful for development/testing and as a fallback. |
| 7 | Shared database or separate? | **Shared** | Same SQLite file, WAL mode. Separate DB is unnecessary complexity. |

---

## 11. Open Questions

New questions introduced by the revised architecture:

1. **`_makeLocalRequest()` vs reusing `_makeRequest()` with URL override.**
   The plan recommends a separate method to avoid proxy/TLS/retry logic.
   Alternative: add a `baseUrlOverride` parameter to `_makeRequest()`.  The
   separate method is simpler and more explicit -- but if the team prefers
   consistency, the override approach works too.  **Recommendation:** separate
   method.

2. **`dbUtils.getTimestampMinusSeconds()` availability.**  The
   `deleteProcessedOlderThan` method needs a portable way to compute
   "now minus N seconds."  Check if `internal/database/utils.py` provides
   this.  If not, compute it via:
   ```python
   import datetime
   cutoff = dbUtils.getCurrentTimestamp()  # returns formatted string
   # ... or compute from datetime and format consistently
   ```
   The implementer should verify the exact utility available.

3. **httpx timeout on `_makeLocalRequest()`.**  The method uses
   `self.timeout + 10` (40s by default) to give margin over the 30s
   long-poll timeout.  Is this sufficient, or should it use the `timeout`
   query parameter value + margin?  **Recommendation:** use `self.timeout + 10`
   for simplicity; the long-poll endpoint returns within `timeout` seconds
   by design.

---

## 12. Documentation Impact

When this feature lands, the following docs must be updated:

| Document | Changes |
|----------|---------|
| `docs/database-schema.md` | Add `webhook_updates` table definition |
| `docs/database-schema-llm.md` | Add `webhook_updates` table (keep in sync with above) |
| `docs/llm/database.md` | Add `WebhookUpdatesRepository` to repository listing |
| `docs/llm/architecture.md` | Add webhook receiver as a separate process in architecture overview; describe the local API proxy pattern |
| `docs/llm/configuration.md` | Document `[webhook-receiver]` config section with all keys |
| `docs/llm/libraries.md` | Note `aiohttp` as a direct dependency (promoted from transitive) |
| `docs/llm/index.md` | Update stack snapshot if architecture description changes |
| `docs/developer-guide.md` | Add section on running the webhook receiver process |
| `AGENTS.md` | Add note about `internal/max_webhook_receiver/` and two-process deployment |
| `README.md` | Add webhook setup instructions for end users |

Load the `update-project-docs` skill during the documentation step of
implementation.
