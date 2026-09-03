"""Tests for the Max webhook receiver aiohttp application.

Exercises the ``POST /webhook`` and ``GET /updates`` handlers through an
in-process :class:`aiohttp.test_utils.TestClient` backed by a fully mocked
:class:`WebhookUpdatesRepository`, so no real listening socket or SQLite file
is touched.

The mock repository is wired so the application's lifecycle hooks
(``ensureSchema`` / ``closeDatabase`` / the background cleanup task) and the
two request handlers all resolve to no-op awaits, letting each test override
only the repository behaviour it cares about.
"""

import asyncio
import datetime
import json
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lib.db.manager import DatabaseManager
from lib.max_webhook_receiver import app as appModule
from lib.max_webhook_receiver.app import ENABLE_CLEANUP_KEY, SECRET_HEADER, createApp
from lib.max_webhook_receiver.models import WebhookUpdatesRow
from lib.max_webhook_receiver.repository import WebhookUpdatesRepository

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


def _makeMockRepository() -> MagicMock:
    """Build a fully-mocked WebhookUpdatesRepository (all five methods no-op)."""
    repository = MagicMock(spec=WebhookUpdatesRepository)
    repository.addUpdate = AsyncMock(return_value=True)
    repository.getUnprocessedUpdates = AsyncMock(return_value=[])
    repository.markProcessed = AsyncMock(return_value=None)
    repository.markProcessedBeforeMarker = AsyncMock(return_value=None)
    repository.deleteProcessedOlderThan = AsyncMock(return_value=None)
    return repository


def _makeMockManager() -> MagicMock:
    """Build a mocked DatabaseManager with an awaitable-execute provider.

    Unspec'd on purpose: DatabaseManager uses __slots__, and the project
    mock convention for slotted classes is unspec'd MagicMock children
    (see project memory on Database/DatabaseManager mocking).
    """
    manager = MagicMock()
    provider = MagicMock()
    provider.execute = AsyncMock(return_value=None)  # ensureSchema awaits this
    manager.getProvider = AsyncMock(return_value=provider)
    manager.closeAll = AsyncMock(return_value=None)
    return manager


def _buildApp(
    mockRepository: MagicMock,
    mockManager: MagicMock,
    secret: str = WEBHOOK_SECRET,
    getUpdatesSecret: str = "",
    enableCleanup: bool = True,
    markOnSubsequentPoll: bool = True,
) -> web.Application:
    """Assemble a receiver app from a mock repository and manager, localising the type cast.

    Args:
        mockRepository: Mock repository produced by :func:`_makeMockRepository`.
        mockManager: Mock manager produced by :func:`_makeMockManager`.
        secret: Shared secret for the webhook POST endpoint.
        getUpdatesSecret: Optional guard for ``GET /updates`` (empty disables).
        enableCleanup: Whether the background cleanup task reaps old rows.
        markOnSubsequentPoll: Deferred-acknowledgement mode toggle for
            ``GET /updates`` (True = at-least-once, False = at-most-once).

    Returns:
        A configured :class:`aiohttp.web.Application` ready for ``TestServer``.
    """
    return createApp(
        repository=cast(WebhookUpdatesRepository, mockRepository),
        manager=cast(DatabaseManager, mockManager),
        secret=secret,
        getUpdatesSecret=getUpdatesSecret,
        webhookPath=WEBHOOK_PATH,
        enableCleanup=enableCleanup,
        markOnSubsequentPoll=markOnSubsequentPoll,
    )


class TestWebhookPostHandler:
    """Tests for ``POST /webhook``: secret check, storage, and error paths."""

    async def testValidRequestReturns200(self) -> None:
        """A well-formed POST with the correct secret answers ``{"ok": true}``."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        app = _buildApp(mockRepository, mockManager)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                WEBHOOK_PATH, headers={SECRET_HEADER: WEBHOOK_SECRET}, json={"update_type": "message_created"}
            )
            assert resp.status == 200
            payload = await resp.json()
            assert payload == {"ok": True}

    async def testValidRequestStoresInDb(self) -> None:
        """A valid POST persists ``updateType`` and the raw JSON body verbatim."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        app = _buildApp(mockRepository, mockManager)
        body = {"update_type": "message_created", "data": {"hello": "world"}}
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, headers={SECRET_HEADER: WEBHOOK_SECRET}, json=body)
            assert resp.status == 200
        mockRepository.addUpdate.assert_awaited_once()
        recordedArgs = mockRepository.addUpdate.await_args
        assert recordedArgs is not None
        callKwargs = recordedArgs.kwargs
        assert callKwargs["updateType"] == "message_created"
        assert json.loads(callKwargs["rawJson"]) == body

    async def testInvalidSecretReturns403(self) -> None:
        """A wrong secret header is rejected before any storage attempt."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        app = _buildApp(mockRepository, mockManager)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, headers={SECRET_HEADER: "wrong"}, json={})
            assert resp.status == 403
        mockRepository.addUpdate.assert_not_awaited()

    async def testMissingSecretHeaderReturns403(self) -> None:
        """An absent secret header is treated as forbidden."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        app = _buildApp(mockRepository, mockManager)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, json={})
            assert resp.status == 403
        mockRepository.addUpdate.assert_not_awaited()

    async def testMalformedJsonReturns400(self) -> None:
        """An unparseable body yields 400 and never reaches the repository."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        app = _buildApp(mockRepository, mockManager)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, headers={SECRET_HEADER: WEBHOOK_SECRET}, data="not a json")
            assert resp.status == 400
        mockRepository.addUpdate.assert_not_awaited()

    async def testNonDictJsonReturns400(self) -> None:
        """A valid JSON array is rejected: only JSON objects are accepted."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        app = _buildApp(mockRepository, mockManager)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, headers={SECRET_HEADER: WEBHOOK_SECRET}, json=[1, 2, 3])
            assert resp.status == 400
        mockRepository.addUpdate.assert_not_awaited()

    async def testDbWriteFailureReturns500(self) -> None:
        """A failed ``addUpdate`` returns 500 so Max retries delivery.

        Answering 200 on a DB write failure would permanently lose the update
        (Max never retries a 200). The receiver must surface 500 so the
        webhook is redelivered.
        """
        mockRepository = _makeMockRepository()
        mockRepository.addUpdate = AsyncMock(return_value=False)
        mockManager = _makeMockManager()
        app = _buildApp(mockRepository, mockManager)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(WEBHOOK_PATH, headers={SECRET_HEADER: WEBHOOK_SECRET}, json={"update_type": "x"})
            assert resp.status == 500


class TestGetUpdatesHandler:
    """Tests for ``GET /updates``: delivery, marking, limit, and auth."""

    async def testReturnsUnprocessedUpdates(self) -> None:
        """In deferred mode (default) rows are returned with a compound marker.

        The marker is ``"{received_at}|{id}"`` built from the last served row,
        not ``None``; rows are left pending (markProcessed not called) so a bot
        crash before the next poll re-delivers them.
        """
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        rows = [
            _makeWebhookRow("id-1", json.dumps({"update_type": "a", "seq": 1})),
            _makeWebhookRow("id-2", json.dumps({"update_type": "b", "seq": 2})),
        ]
        mockRepository.getUnprocessedUpdates = AsyncMock(return_value=rows)
        app = _buildApp(mockRepository, mockManager)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(UPDATES_PATH)
            assert resp.status == 200
            payload = await resp.json()
            assert [u["seq"] for u in payload["updates"]] == [1, 2]
            expectedMarker = f"{rows[-1]['received_at'].isoformat()}|id-2"
            assert payload["marker"] == expectedMarker
        # Deferred mode: served rows are NOT marked on read.
        mockRepository.markProcessed.assert_not_awaited()

    async def testDeferredMode_doesNotMarkOnFirstPoll(self) -> None:
        """First poll (no marker) serves rows without acking anything."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        rows = [_makeWebhookRow("id-99", json.dumps({"update_type": "a"}))]
        mockRepository.getUnprocessedUpdates = AsyncMock(return_value=rows)
        app = _buildApp(mockRepository, mockManager)
        async with TestClient(TestServer(app)) as client:
            await client.get(UPDATES_PATH)
        mockRepository.markProcessed.assert_not_awaited()
        mockRepository.markProcessedBeforeMarker.assert_not_awaited()
        # Fetch used no marker filter on the first poll.
        fetchArgs = mockRepository.getUnprocessedUpdates.await_args
        assert fetchArgs is not None
        assert fetchArgs.kwargs.get("marker") is None

    async def testDeferredMode_marksOnSubsequentPoll(self) -> None:
        """Second poll passes the prior marker -> markProcessedBeforeMarker acks it."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        rows = [_makeWebhookRow("id-1", json.dumps({"update_type": "a"}))]
        mockRepository.getUnprocessedUpdates = AsyncMock(return_value=rows)
        app = _buildApp(mockRepository, mockManager)
        marker = f"{rows[0]['received_at'].isoformat()}|id-1"
        async with TestClient(TestServer(app)) as client:
            await client.get(UPDATES_PATH, params={"marker": marker})
        mockRepository.markProcessedBeforeMarker.assert_awaited_once_with(marker)
        # Immediate marking is still not used in deferred mode.
        mockRepository.markProcessed.assert_not_awaited()

    async def testImmediateMode_marksOnRead(self) -> None:
        """With markOnSubsequentPoll=False, rows are marked on read (at-most-once)."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        rows = [_makeWebhookRow("id-42", json.dumps({"update_type": "a"}))]
        mockRepository.getUnprocessedUpdates = AsyncMock(return_value=rows)
        app = _buildApp(mockRepository, mockManager, markOnSubsequentPoll=False)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(UPDATES_PATH)
            payload = await resp.json()
        mockRepository.markProcessed.assert_awaited_once_with(["id-42"])
        mockRepository.markProcessedBeforeMarker.assert_not_awaited()
        assert payload["marker"] is not None

    async def testEmptyDbReturnsEmptyList(self) -> None:
        """With no rows and ``timeout=0`` the endpoint returns an empty list."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        mockRepository.getUnprocessedUpdates = AsyncMock(return_value=[])
        app = _buildApp(mockRepository, mockManager)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"{UPDATES_PATH}?timeout=0")
            assert resp.status == 200
            payload = await resp.json()
            assert payload["updates"] == []
            # The empty-result path echoes the ``marker`` query param (default "").
            assert payload["marker"] == ""

    async def testEmptyPollReturnsCleansedMarkerOnBadMarker(self) -> None:
        """A bad marker cleansed to None is echoed back as ``""``, not the raw value.

        Regression: when ``markProcessedBeforeMarker`` raises on a malformed
        marker, the handler resets ``markerParam`` to None and continues. The
        empty-result path must echo the cleansed marker (empty string), not the
        original bad query value — otherwise the bot re-sends the bad marker
        forever and never recovers.
        """
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        mockRepository.markProcessedBeforeMarker = AsyncMock(side_effect=ValueError("bad marker"))
        mockRepository.getUnprocessedUpdates = AsyncMock(return_value=[])
        app = _buildApp(mockRepository, mockManager)
        badMarker = "not-a-real-marker"
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(UPDATES_PATH, params={"marker": badMarker, "timeout": "0"})
            assert resp.status == 200
            payload = await resp.json()
            assert payload["updates"] == []
            # Cleansed to "" — NOT the raw bad marker.
            assert payload["marker"] == ""

    async def testLimitParamRespected(self) -> None:
        """The ``limit`` query param is forwarded to the repository call."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        mockRepository.getUnprocessedUpdates = AsyncMock(return_value=[])
        app = _buildApp(mockRepository, mockManager)
        async with TestClient(TestServer(app)) as client:
            await client.get(f"{UPDATES_PATH}?limit=5&timeout=0")
        mockRepository.getUnprocessedUpdates.assert_awaited_once_with(limit=5, marker=None)

    async def testOptionalAuthRejectsBadSecret(self) -> None:
        """When ``getUpdatesSecret`` is set, a missing Authorization is 403."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        mockRepository.getUnprocessedUpdates = AsyncMock(return_value=[])
        app = _buildApp(mockRepository, mockManager, getUpdatesSecret=GET_UPDATES_SECRET)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(UPDATES_PATH)
            assert resp.status == 403
        mockRepository.getUnprocessedUpdates.assert_not_awaited()

    async def testOptionalAuthAllowsWhenSecretEmpty(self) -> None:
        """With no ``getUpdatesSecret`` the endpoint is open without auth."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        mockRepository.getUnprocessedUpdates = AsyncMock(return_value=[])
        app = _buildApp(mockRepository, mockManager, getUpdatesSecret="")
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"{UPDATES_PATH}?timeout=0")
            assert resp.status == 200


class TestDefaultProviderUsage:
    """The app routes repository calls via the receiver's OWN manager default.

    With ``datasource`` gone (D13), handlers call repository methods without
    ``dataSource``; the calls resolve to the default provider of the
    receiver's own ``DatabaseManager`` (D12) — never into the bot's
    ``[database.providers]`` map.
    """

    async def testRepositoryCallsOmitDataSource(self) -> None:
        """POST and GET call repository methods with no ``dataSource`` kwarg."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        app = _buildApp(mockRepository, mockManager)
        async with TestClient(TestServer(app)) as client:
            await client.post(
                WEBHOOK_PATH,
                headers={SECRET_HEADER: WEBHOOK_SECRET},
                json={"update_type": "message_created"},
            )
            await client.get(f"{UPDATES_PATH}?limit=5&timeout=0")
        addArgs = mockRepository.addUpdate.await_args
        assert addArgs is not None
        assert "dataSource" not in addArgs.kwargs
        getArgs = mockRepository.getUnprocessedUpdates.await_args
        assert getArgs is not None
        assert "dataSource" not in getArgs.kwargs


class TestEnableCleanup:
    """Tests for the ``enable-cleanup`` config: toggling the reap loop.

    The cleanup task always sleeps between sweeps, but the deletion step is
    skipped when ``enableCleanup`` is False so all rows are retained (useful
    for debugging). These tests drive ``cleanupTask`` directly with a stubbed
    ``asyncio.sleep`` so the 300s interval does not stall the suite.
    """

    async def testCreateAppStoresEnableCleanupFlag(self) -> None:
        """createApp stores the enableCleanup flag (default True) in the app."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        appEnabled = _buildApp(mockRepository, mockManager)
        assert appEnabled[ENABLE_CLEANUP_KEY] is True

        appDisabled = _buildApp(mockRepository, mockManager, enableCleanup=False)
        assert appDisabled[ENABLE_CLEANUP_KEY] is False

    async def testCleanupTask_disabledSkipsDelete(self) -> None:
        """With enableCleanup=False, deleteProcessedOlderThan is never called."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        app = _buildApp(mockRepository, mockManager, enableCleanup=False)

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
        mockRepository.deleteProcessedOlderThan.assert_not_awaited()

    async def testCleanupTask_enabledCallsDelete(self) -> None:
        """With enableCleanup=True, each sweep calls deleteProcessedOlderThan."""
        mockRepository = _makeMockRepository()
        mockManager = _makeMockManager()
        app = _buildApp(mockRepository, mockManager, enableCleanup=True)

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
        assert mockRepository.deleteProcessedOlderThan.await_count == 2
