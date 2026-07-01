"""Tests for the Max webhook receiver aiohttp application.

Exercises the ``POST /webhook`` and ``GET /updates`` handlers through an
in-process :class:`aiohttp.test_utils.TestClient` backed by a fully mocked
:class:`Database`, so no real listening socket or SQLite file is touched.

The mock database is wired so the application's lifecycle hooks
(``warmUpDatabase`` / ``closeDatabase`` / the background cleanup task) and the
two request handlers all resolve to no-op awaits, letting each test override
only the repository behaviour it cares about.
"""

import asyncio
import datetime
import json
from typing import Optional, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from internal.database import Database
from internal.database.models import WebhookUpdatesRow
from internal.max_webhook_receiver.app import SECRET_HEADER, createApp

WEBHOOK_SECRET = "test-secret"
"""Shared secret used for the ``X-Max-Bot-Api-Secret`` header in POST tests."""

GET_UPDATES_SECRET = "auth-secret"
"""Secret guarding the ``GET /updates`` endpoint in the auth-gated tests."""

WEBHOOK_PATH = "/webhook"
"""URL path registered for the webhook POST handler."""

UPDATES_PATH = "/updates"
"""URL path registered for the get-updates handler."""


def _makeWebhookRow(rowId: str, rawJson: str, updateType: str = "message_created") -> WebhookUpdatesRow:
    """Build a minimal :class:`WebhookUpdatesRow` for the GET handler tests.

    Args:
        rowId: Value for the row's ``id`` field (consumed by ``markProcessed``).
        rawJson: Serialized JSON string served back as a single update.
        updateType: Coarse ``update_type`` tag stored alongside the payload.

    Returns:
        A complete :class:`WebhookUpdatesRow` dict.
    """
    now = datetime.datetime.now()
    return {
        "id": rowId,
        "received_at": now,
        "update_type": updateType,
        "raw_json": rawJson,
        "processed": 0,
        "processed_at": None,
    }


def _makeMockDatabase() -> MagicMock:
    """Create a fully-mocked :class:`Database` for the webhook receiver.

    The mock exposes the ``webhookUpdates`` repository and ``manager`` touched
    by the handlers and lifecycle hooks, each method defaulting to a no-op or
    empty result so tests only override what they assert on.

    Returns:
        A :class:`MagicMock` spec'd against :class:`Database`, suitable for
        passing to :func:`_buildApp`.
    """
    db = MagicMock(spec=Database)
    db.webhookUpdates = MagicMock()
    db.webhookUpdates.addUpdate = AsyncMock(return_value=True)
    db.webhookUpdates.getUnprocessedUpdates = AsyncMock(return_value=[])
    db.webhookUpdates.markProcessed = AsyncMock(return_value=None)
    db.webhookUpdates.markProcessedBeforeMarker = AsyncMock(return_value=None)
    db.webhookUpdates.deleteProcessedOlderThan = AsyncMock(return_value=None)
    db.manager = MagicMock()
    db.manager.getProvider = AsyncMock(return_value=MagicMock())
    db.manager.closeAll = AsyncMock(return_value=None)
    return db


def _buildApp(
    mockDb: MagicMock,
    secret: str = WEBHOOK_SECRET,
    getUpdatesSecret: str = "",
    datasource: Optional[str] = None,
    enableCleanup: bool = True,
    markOnSubsequentPoll: bool = True,
) -> web.Application:
    """Assemble a receiver app from a mock database, localising the type cast.

    Args:
        mockDb: Mock database produced by :func:`_makeMockDatabase`.
        secret: Shared secret for the webhook POST endpoint.
        getUpdatesSecret: Optional guard for ``GET /updates`` (empty disables).
        datasource: Optional data source name forwarded to repository calls.
        enableCleanup: Whether the background cleanup task reaps old rows.
        markOnSubsequentPoll: Deferred-acknowledgement mode toggle for
            ``GET /updates`` (True = at-least-once, False = at-most-once).

    Returns:
        A configured :class:`aiohttp.web.Application` ready for ``TestServer``.
    """
    return createApp(
        database=cast(Database, mockDb),
        secret=secret,
        getUpdatesSecret=getUpdatesSecret,
        webhookPath=WEBHOOK_PATH,
        datasource=datasource,
        enableCleanup=enableCleanup,
        markOnSubsequentPoll=markOnSubsequentPoll,
    )


class TestWebhookPostHandler:
    """Tests for ``POST /webhook``: secret check, storage, and error paths."""

    async def testValidRequestReturns200(self) -> None:
        """A well-formed POST with the correct secret answers ``{"ok": true}``."""
        mockDb = _makeMockDatabase()
        app = _buildApp(mockDb)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                WEBHOOK_PATH, headers={SECRET_HEADER: WEBHOOK_SECRET}, json={"update_type": "message_created"}
            )
            assert resp.status == 200
            payload = await resp.json()
            assert payload == {"ok": True}

    async def testValidRequestStoresInDb(self) -> None:
        """A valid POST persists ``updateType`` and the raw JSON body verbatim."""
        mockDb = _makeMockDatabase()
        app = _buildApp(mockDb)
        body = {"update_type": "message_created", "data": {"hello": "world"}}
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, headers={SECRET_HEADER: WEBHOOK_SECRET}, json=body)
            assert resp.status == 200
        mockDb.webhookUpdates.addUpdate.assert_awaited_once()
        recordedArgs = mockDb.webhookUpdates.addUpdate.await_args
        assert recordedArgs is not None
        callKwargs = recordedArgs.kwargs
        assert callKwargs["updateType"] == "message_created"
        assert json.loads(callKwargs["rawJson"]) == body

    async def testInvalidSecretReturns403(self) -> None:
        """A wrong secret header is rejected before any storage attempt."""
        mockDb = _makeMockDatabase()
        app = _buildApp(mockDb)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, headers={SECRET_HEADER: "wrong"}, json={})
            assert resp.status == 403
        mockDb.webhookUpdates.addUpdate.assert_not_awaited()

    async def testMissingSecretHeaderReturns403(self) -> None:
        """An absent secret header is treated as forbidden."""
        mockDb = _makeMockDatabase()
        app = _buildApp(mockDb)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, json={})
            assert resp.status == 403
        mockDb.webhookUpdates.addUpdate.assert_not_awaited()

    async def testMalformedJsonReturns400(self) -> None:
        """An unparseable body yields 400 and never reaches the repository."""
        mockDb = _makeMockDatabase()
        app = _buildApp(mockDb)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, headers={SECRET_HEADER: WEBHOOK_SECRET}, data="not a json")
            assert resp.status == 400
        mockDb.webhookUpdates.addUpdate.assert_not_awaited()

    async def testNonDictJsonReturns400(self) -> None:
        """A valid JSON array is rejected: only JSON objects are accepted."""
        mockDb = _makeMockDatabase()
        app = _buildApp(mockDb)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, headers={SECRET_HEADER: WEBHOOK_SECRET}, json=[1, 2, 3])
            assert resp.status == 400
        mockDb.webhookUpdates.addUpdate.assert_not_awaited()

    async def testDbWriteFailureReturns200(self) -> None:
        """A failed ``addUpdate`` is swallowed so Max does not retry delivery."""
        mockDb = _makeMockDatabase()
        mockDb.webhookUpdates.addUpdate = AsyncMock(return_value=False)
        app = _buildApp(mockDb)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, headers={SECRET_HEADER: WEBHOOK_SECRET}, json={"update_type": "x"})
            assert resp.status == 200


class TestGetUpdatesHandler:
    """Tests for ``GET /updates``: delivery, marking, limit, and auth."""

    async def testReturnsUnprocessedUpdates(self) -> None:
        """In deferred mode (default) rows are returned with a compound marker.

        The marker is ``"{received_at}|{id}"`` built from the last served row,
        not ``None``; rows are left pending (markProcessed not called) so a bot
        crash before the next poll re-delivers them.
        """
        mockDb = _makeMockDatabase()
        rows = [
            _makeWebhookRow("id-1", json.dumps({"update_type": "a", "seq": 1})),
            _makeWebhookRow("id-2", json.dumps({"update_type": "b", "seq": 2})),
        ]
        mockDb.webhookUpdates.getUnprocessedUpdates = AsyncMock(return_value=rows)
        app = _buildApp(mockDb)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(UPDATES_PATH)
            assert resp.status == 200
            payload = await resp.json()
            assert [u["seq"] for u in payload["updates"]] == [1, 2]
            expectedMarker = f"{rows[-1]['received_at'].isoformat()}|id-2"
            assert payload["marker"] == expectedMarker
        # Deferred mode: served rows are NOT marked on read.
        mockDb.webhookUpdates.markProcessed.assert_not_awaited()

    async def testDeferredMode_doesNotMarkOnFirstPoll(self) -> None:
        """First poll (no marker) serves rows without acking anything."""
        mockDb = _makeMockDatabase()
        rows = [_makeWebhookRow("id-99", json.dumps({"update_type": "a"}))]
        mockDb.webhookUpdates.getUnprocessedUpdates = AsyncMock(return_value=rows)
        app = _buildApp(mockDb)
        async with TestClient(TestServer(app)) as client:
            await client.get(UPDATES_PATH)
        mockDb.webhookUpdates.markProcessed.assert_not_awaited()
        mockDb.webhookUpdates.markProcessedBeforeMarker.assert_not_awaited()
        # Fetch used no marker filter on the first poll.
        fetchArgs = mockDb.webhookUpdates.getUnprocessedUpdates.await_args
        assert fetchArgs is not None
        assert fetchArgs.kwargs.get("marker") is None

    async def testDeferredMode_marksOnSubsequentPoll(self) -> None:
        """Second poll passes the prior marker -> markProcessedBeforeMarker acks it."""
        mockDb = _makeMockDatabase()
        rows = [_makeWebhookRow("id-1", json.dumps({"update_type": "a"}))]
        mockDb.webhookUpdates.getUnprocessedUpdates = AsyncMock(return_value=rows)
        app = _buildApp(mockDb)
        marker = f"{rows[0]['received_at'].isoformat()}|id-1"
        async with TestClient(TestServer(app)) as client:
            await client.get(UPDATES_PATH, params={"marker": marker})
        mockDb.webhookUpdates.markProcessedBeforeMarker.assert_awaited_once_with(marker, dataSource=None)
        # Immediate marking is still not used in deferred mode.
        mockDb.webhookUpdates.markProcessed.assert_not_awaited()

    async def testImmediateMode_marksOnRead(self) -> None:
        """With markOnSubsequentPoll=False, rows are marked on read (at-most-once)."""
        mockDb = _makeMockDatabase()
        rows = [_makeWebhookRow("id-42", json.dumps({"update_type": "a"}))]
        mockDb.webhookUpdates.getUnprocessedUpdates = AsyncMock(return_value=rows)
        app = _buildApp(mockDb, markOnSubsequentPoll=False)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(UPDATES_PATH)
            payload = await resp.json()
        mockDb.webhookUpdates.markProcessed.assert_awaited_once_with(["id-42"], dataSource=None)
        mockDb.webhookUpdates.markProcessedBeforeMarker.assert_not_awaited()
        # Immediate mode returns marker: None and ignores any supplied marker.
        assert payload["marker"] is None

    async def testEmptyDbReturnsEmptyList(self) -> None:
        """With no rows and ``timeout=0`` the endpoint returns an empty list."""
        mockDb = _makeMockDatabase()
        mockDb.webhookUpdates.getUnprocessedUpdates = AsyncMock(return_value=[])
        app = _buildApp(mockDb)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"{UPDATES_PATH}?timeout=0")
            assert resp.status == 200
            payload = await resp.json()
            assert payload["updates"] == []
            # The empty-result path echoes the ``marker`` query param (default "").
            assert payload["marker"] == ""

    async def testLimitParamRespected(self) -> None:
        """The ``limit`` query param is forwarded to the repository call."""
        mockDb = _makeMockDatabase()
        mockDb.webhookUpdates.getUnprocessedUpdates = AsyncMock(return_value=[])
        app = _buildApp(mockDb)
        async with TestClient(TestServer(app)) as client:
            await client.get(f"{UPDATES_PATH}?limit=5&timeout=0")
        mockDb.webhookUpdates.getUnprocessedUpdates.assert_awaited_once_with(limit=5, marker=None, dataSource=None)

    async def testOptionalAuthRejectsBadSecret(self) -> None:
        """When ``getUpdatesSecret`` is set, a missing Authorization is 403."""
        mockDb = _makeMockDatabase()
        mockDb.webhookUpdates.getUnprocessedUpdates = AsyncMock(return_value=[])
        app = _buildApp(mockDb, getUpdatesSecret=GET_UPDATES_SECRET)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(UPDATES_PATH)
            assert resp.status == 403
        mockDb.webhookUpdates.getUnprocessedUpdates.assert_not_awaited()

    async def testOptionalAuthAllowsWhenSecretEmpty(self) -> None:
        """With no ``getUpdatesSecret`` the endpoint is open without auth."""
        mockDb = _makeMockDatabase()
        mockDb.webhookUpdates.getUnprocessedUpdates = AsyncMock(return_value=[])
        app = _buildApp(mockDb, getUpdatesSecret="")
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"{UPDATES_PATH}?timeout=0")
            assert resp.status == 200


class TestDataSourceForwarding:
    """Tests for the ``datasource`` config: forwarding to repository calls.

    The receiver must route every repository call through the configured data
    source so webhook updates can live in a separate database from the main
    bot. ``createApp(datasource=...)`` stores the name in the app dict and the
    handlers pass it as ``dataSource=...`` to each repository method.
    """

    async def testPostForwardsDataSourceToAddUpdate(self) -> None:
        """A POST forwards the configured dataSource to ``addUpdate``."""
        mockDb = _makeMockDatabase()
        app = _buildApp(mockDb, datasource="webhook-db")
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                WEBHOOK_PATH,
                headers={SECRET_HEADER: WEBHOOK_SECRET},
                json={"update_type": "message_created"},
            )
            assert resp.status == 200
        mockDb.webhookUpdates.addUpdate.assert_awaited_once()
        addArgs = mockDb.webhookUpdates.addUpdate.await_args
        assert addArgs is not None
        assert addArgs.kwargs["dataSource"] == "webhook-db"

    async def testGetUpdatesForwardsDataSource(self) -> None:
        """A GET forwards the configured dataSource to fetch + ack calls.

        In deferred mode (default) the ack call is ``markProcessedBeforeMarker``
        (triggered when the bot passes a marker), not ``markProcessed``.
        """
        mockDb = _makeMockDatabase()
        rows = [_makeWebhookRow("id-1", json.dumps({"update_type": "a"}))]
        mockDb.webhookUpdates.getUnprocessedUpdates = AsyncMock(return_value=rows)
        app = _buildApp(mockDb, datasource="webhook-db")
        marker = f"{rows[0]['received_at'].isoformat()}|id-1"
        async with TestClient(TestServer(app)) as client:
            await client.get(UPDATES_PATH, params={"marker": marker})
        fetchArgs = mockDb.webhookUpdates.getUnprocessedUpdates.await_args
        ackArgs = mockDb.webhookUpdates.markProcessedBeforeMarker.await_args
        assert fetchArgs is not None
        assert ackArgs is not None
        assert fetchArgs.kwargs["dataSource"] == "webhook-db"
        assert ackArgs.kwargs["dataSource"] == "webhook-db"

    async def testEmptyDataSourceDefaultsToNone(self) -> None:
        """Omitting datasource stores None so the default provider is used."""
        mockDb = _makeMockDatabase()
        app = _buildApp(mockDb)
        assert app["dataSource"] is None


class TestEnableCleanup:
    """Tests for the ``enable-cleanup`` config: toggling the reap loop.

    The cleanup task always sleeps between sweeps, but the deletion step is
    skipped when ``enableCleanup`` is False so all rows are retained (useful
    for debugging). These tests drive ``cleanupTask`` directly with a stubbed
    ``asyncio.sleep`` so the 300s interval does not stall the suite.
    """

    async def testCreateAppStoresEnableCleanupFlag(self) -> None:
        """createApp stores the enableCleanup flag (default True) in the app."""
        mockDb = _makeMockDatabase()
        appEnabled = _buildApp(mockDb)
        assert appEnabled["enableCleanup"] is True

        appDisabled = _buildApp(mockDb, enableCleanup=False)
        assert appDisabled["enableCleanup"] is False

    async def testCleanupTask_disabledSkipsDelete(self) -> None:
        """With enableCleanup=False, deleteProcessedOlderThan is never called."""
        from internal.max_webhook_receiver import app as appModule

        mockDb = _makeMockDatabase()
        app = _buildApp(mockDb, enableCleanup=False)

        sleepCount = 0

        async def fastSleep(_seconds: float) -> None:
            nonlocal sleepCount
            sleepCount += 1
            # Let a couple of sweeps happen (verifying the skip is stable, not
            # just a one-shot), then cancel out of the loop.
            if sleepCount >= 3:
                raise asyncio.CancelledError()

        with (
            patch.object(appModule, "asyncio") as mockAsyncio,
            pytest.raises(asyncio.CancelledError),
        ):
            mockAsyncio.sleep = fastSleep
            mockAsyncio.CancelledError = asyncio.CancelledError
            await appModule.cleanupTask(app)

        # At least two iterations passed through the `continue` branch without
        # ever touching the repository.
        assert sleepCount >= 2
        mockDb.webhookUpdates.deleteProcessedOlderThan.assert_not_awaited()

    async def testCleanupTask_enabledCallsDelete(self) -> None:
        """With enableCleanup=True, each sweep calls deleteProcessedOlderThan."""
        from internal.max_webhook_receiver import app as appModule

        mockDb = _makeMockDatabase()
        app = _buildApp(mockDb, enableCleanup=True)

        sleepCount = 0

        async def fastSleep(_seconds: float) -> None:
            nonlocal sleepCount
            sleepCount += 1
            if sleepCount >= 3:
                raise asyncio.CancelledError()

        with (
            patch.object(appModule, "asyncio") as mockAsyncio,
            pytest.raises(asyncio.CancelledError),
        ):
            mockAsyncio.sleep = fastSleep
            mockAsyncio.CancelledError = asyncio.CancelledError
            await appModule.cleanupTask(app)

        # Two successful sweeps each deleted, then the third sleep cancelled.
        assert mockDb.webhookUpdates.deleteProcessedOlderThan.await_count == 2
