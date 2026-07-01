"""aiohttp web application for the Max webhook receiver.

Defines the HTTP handlers, the background cleanup task, and the
:func:`createApp` factory that assembles the standalone webhook receiver
process.

Endpoints:

    POST ``<webhookPath>``
        Receives raw webhook POSTs from the Max API. The shared secret is
        verified via the ``X-Max-Bot-Api-Secret`` header and the body is
        stored verbatim in the ``webhook_updates`` table.

    GET ``/updates``
        Serves stored updates back to the bot using the Max API protocol
        (``{"updates": [...], "marker": ...}``). Two delivery modes are
        supported, selected by ``mark-on-subsequent-poll``: immediate mode
        marks fetched rows processed on read (at-most-once), while deferred
        mode leaves them pending until the bot passes the returned marker back
        on its next poll (at-least-once). When no updates are available the
        request long-polls up to ``timeout`` seconds before returning empty.
"""

import asyncio
import hmac
import json
import logging
import time
import uuid
from typing import List, Optional

from aiohttp import web

from internal.database import Database

logger = logging.getLogger(__name__)

SECRET_HEADER = "X-Max-Bot-Api-Secret"
"""HTTP header carrying the shared webhook secret, sent by the Max API on every POST."""

CLEANUP_INTERVAL_SECONDS = 300
"""Seconds between cleanup sweeps of processed webhook updates."""

CLEANUP_TTL_SECONDS = 3600
"""Processed updates older than this TTL (in seconds) are deleted."""

POLL_INTERVAL = 0.5
"""Seconds between re-checks of the database during a long-poll request."""


def _clampIntParam(value: Optional[str], default: int, low: int, high: int) -> int:
    """Parse an integer query parameter and clamp it to ``[low, high]``.

    Args:
        value: Raw string value from the query string, or None when absent.
        default: Value to use when ``value`` is None or not a valid integer.
        low: Minimum allowed value (inclusive).
        high: Maximum allowed value (inclusive).

    Returns:
        The parsed integer clamped to ``[low, high]``, or ``default`` (clamped)
        when the input is absent or unparseable.
    """
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


async def handleWebhook(request: web.Request) -> web.Response:
    """Handle incoming webhook POSTs from the Max API.

    Verifies the shared secret with a constant-time comparison, parses the
    JSON body, stores the raw payload, and returns 200. A failed database
    write is logged but still answered 200 so the Max API does not retry the
    delivery for a transient local failure.

    Args:
        request: Incoming aiohttp request carrying the raw webhook body.

    Returns:
        JSON response: 403 on a bad secret, 400 on malformed JSON, 200
        otherwise.
    """
    database: Database = request.app["database"]
    webhookSecret: str = request.app["webhookSecret"]
    dataSource: Optional[str] = request.app["dataSource"]

    secretHeader = request.headers.get(SECRET_HEADER, "")
    if not hmac.compare_digest(secretHeader, webhookSecret):
        return web.json_response({"error": "forbidden"}, status=403)

    body = await request.read()
    rawBody = body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(rawBody)
    except json.JSONDecodeError as e:
        logger.warning("Malformed webhook body: %s", e)
        return web.json_response({"error": "invalid json"}, status=400)

    if not isinstance(payload, dict):
        logger.warning("Webhook body is not a JSON object")
        return web.json_response({"error": "expected json object"}, status=400)

    updateType = payload.get("update_type") or ""

    stored = await database.webhookUpdates.addUpdate(
        updateId=str(uuid.uuid4()),
        updateType=updateType,
        rawJson=rawBody,
        dataSource=dataSource,
    )
    if not stored:
        logger.error("Failed to store webhook update (updateType=%s)", updateType)

    return web.json_response({"ok": True})


async def handleGetUpdates(request: web.Request) -> web.Response:
    """Serve stored updates to the bot via long polling.

    Speaks the Max API protocol: returns ``{"updates": [...], "marker": ...}``
    where each entry is the parsed webhook payload. Two delivery modes are
    controlled by the app's ``markOnSubsequentPoll`` flag:

    - Immediate mode (``markOnSubsequentPoll = False``): fetched rows are
      marked processed on read, so they are never re-delivered. This is
      at-most-once: a bot crash after the rows are served but before they are
      handled loses them.
    - Deferred mode (``markOnSubsequentPoll = True``, default): fetched rows
      are NOT marked on read. The response carries a compound marker
      (``"{received_at}|{id}"``) describing the last row served. On the next
      poll the bot passes that marker back; only then are all rows at or before
      that position acknowledged via ``markProcessedBeforeMarker``. This is
      at-least-once: a crash between polls leaves the rows unprocessed, so they
      are re-delivered on the next poll.

    When no updates are available the request blocks up to ``timeout`` seconds
    before returning an empty list (echoing the supplied marker back).

    Args:
        request: Incoming aiohttp GET request. Query parameters:

            - ``limit``   -- 1-1000, default 100.
            - ``timeout`` -- 0-90 seconds, default 30.
            - ``marker``  -- opaque compound marker from a previous response.
              In deferred mode, passing it acknowledges the prior batch. When
              no updates are available it is echoed back unchanged.

    Returns:
        JSON response shaped as the Max API ``UpdateList``. 403 when
        ``get-updates-secret`` is set and the ``Authorization`` header
        mismatches.
    """
    app = request.app
    database: Database = app["database"]
    getUpdatesSecret: str = app["getUpdatesSecret"]
    dataSource: Optional[str] = app["dataSource"]
    markOnSubsequent: bool = app["markOnSubsequentPoll"]

    if getUpdatesSecret:
        authHeader = request.headers.get("Authorization", "")
        if not hmac.compare_digest(authHeader, getUpdatesSecret):
            return web.json_response({"error": "unauthorized"}, status=403)

    limit = _clampIntParam(request.query.get("limit"), default=100, low=1, high=1000)
    timeout = _clampIntParam(request.query.get("timeout"), default=30, low=0, high=90)
    marker = request.query.get("marker", "")
    markerParam: Optional[str] = marker or None

    # Deferred mode: acknowledge the previous batch once, up front. A crash
    # before this point leaves those rows unprocessed and they get re-delivered.
    if markOnSubsequent and markerParam is not None:
        await database.webhookUpdates.markProcessedBeforeMarker(markerParam, dataSource=dataSource)

    deadline = time.monotonic() + timeout
    while True:
        rows = await database.webhookUpdates.getUnprocessedUpdates(
            limit=limit,
            marker=markerParam,
            dataSource=dataSource,
        )
        if rows:
            updates = []
            rowIds: List[str] = []
            lastRow = rows[-1]
            for row in rows:
                rowIds.append(row["id"])
                try:
                    updates.append(json.loads(row["raw_json"]))
                except (json.JSONDecodeError, TypeError):
                    logger.error("Skipping corrupt webhook update id=%s", row["id"])
            if not markOnSubsequent:
                # At-most-once: mark the served rows processed immediately.
                await database.webhookUpdates.markProcessed(rowIds, dataSource=dataSource)
            newMarker = f"{lastRow['received_at'].isoformat()}|{lastRow['id']}"
            return web.json_response({"updates": updates, "marker": newMarker})

        if time.monotonic() >= deadline:
            return web.json_response({"updates": [], "marker": marker})

        await asyncio.sleep(POLL_INTERVAL)


async def cleanupTask(app: web.Application) -> None:
    """Periodically delete processed updates older than the TTL.

    Runs an infinite loop: sleeps :data:`CLEANUP_INTERVAL_SECONDS`, then reaps
    processed rows older than :data:`CLEANUP_TTL_SECONDS`. When the app's
    ``enableCleanup`` flag is False, the sleep still runs but the reaping step
    is skipped, keeping all rows indefinitely. Cancellation is honoured for
    graceful shutdown; all other exceptions are logged and the loop continues.

    Args:
        app: The aiohttp application holding the database instance.

    Returns:
        None.
    """
    database: Database = app["database"]
    dataSource: Optional[str] = app["dataSource"]
    enableCleanup: bool = app["enableCleanup"]
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            if not enableCleanup:
                continue
            await database.webhookUpdates.deleteProcessedOlderThan(
                ttlSeconds=CLEANUP_TTL_SECONDS, dataSource=dataSource
            )
        except asyncio.CancelledError:
            logger.info("Webhook cleanup task cancelled")
            raise
        except Exception:
            logger.exception("Error in webhook cleanup task")


async def startCleanupTask(app: web.Application) -> None:
    """Create the background cleanup task on application startup.

    Args:
        app: The aiohttp application to attach the cleanup task to.

    Returns:
        None.
    """
    app["cleanupTask"] = asyncio.create_task(cleanupTask(app))


async def stopCleanupTask(app: web.Application) -> None:
    """Cancel and await the cleanup task on application shutdown.

    Args:
        app: The aiohttp application holding the cleanup task.

    Returns:
        None.
    """
    cleanupTaskInstance: Optional[asyncio.Task[None]] = app.get("cleanupTask")
    if cleanupTaskInstance is not None and not cleanupTaskInstance.done():
        cleanupTaskInstance.cancel()
        try:
            await cleanupTaskInstance
        except asyncio.CancelledError:
            pass


async def warmUpDatabase(app: web.Application) -> None:
    """Warm up the database on startup, running migrations eagerly.

    Forces the default provider to initialise (which runs any pending
    migrations) before the first request is served, so the very first
    webhook POST does not pay the migration cost nor hit a missing table.

    Args:
        app: The aiohttp application holding the database instance.

    Returns:
        None.
    """
    database: Database = app["database"]
    await database.manager.getProvider()  # triggers migrations


async def closeDatabase(app: web.Application) -> None:
    """Close all database providers on shutdown.

    Args:
        app: The aiohttp application holding the database instance.

    Returns:
        None.
    """
    database: Database = app["database"]
    await database.manager.closeAll()


def createApp(
    *,
    database: Database,
    secret: str,
    getUpdatesSecret: str = "",
    webhookPath: str = "/webhook",
    datasource: Optional[str] = None,
    enableCleanup: bool = True,
    markOnSubsequentPoll: bool = True,
) -> web.Application:
    """Build the aiohttp application for the webhook receiver.

    Args:
        database: Initialized :class:`Database` instance used to store and
            serve webhook updates.
        secret: Shared secret expected in the ``X-Max-Bot-Api-Secret`` header
            of every webhook POST.
        getUpdatesSecret: Optional secret for the GET /updates endpoint. When
            non-empty, the endpoint requires a matching ``Authorization``
            header. Empty disables the auth check.
        webhookPath: URL path for the webhook POST endpoint.
        datasource: Optional data source name forwarded to every repository
            call so the receiver can persist webhook updates to a separate
            database from the main bot. None uses the default provider.
        enableCleanup: When True, the background task periodically deletes
            processed updates past the TTL. False keeps all rows indefinitely.
        markOnSubsequentPoll: When True, GET /updates runs in deferred-
            acknowledgement mode (at-least-once): fetched rows are not marked
            processed until the bot passes the returned marker back on the next
            poll. When False, rows are marked processed on read (at-most-once).

    Returns:
        A configured :class:`aiohttp.web.Application` with routes registered
        and lifecycle hooks for the background cleanup task attached.
    """
    app = web.Application()
    app["database"] = database
    app["webhookSecret"] = secret
    app["getUpdatesSecret"] = getUpdatesSecret
    app["dataSource"] = datasource
    app["enableCleanup"] = enableCleanup
    app["markOnSubsequentPoll"] = markOnSubsequentPoll

    app.router.add_post(webhookPath, handleWebhook)
    app.router.add_get("/updates", handleGetUpdates)

    # warmUpDatabase FIRST so migrations run before the cleanup task starts polling.
    app.on_startup.append(warmUpDatabase)
    app.on_startup.append(startCleanupTask)
    app.on_cleanup.append(stopCleanupTask)
    app.on_cleanup.append(closeDatabase)

    return app
