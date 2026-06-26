"""Integration tests for ProxyService singleton."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from internal.services.proxy.service import ProxyService
from lib.proxy import ProxyConfig, ProxyConfigDict


class TestProxyService:
    """Tests for ProxyService singleton."""

    def test_singletonPattern(self):
        """getInstance() returns the same instance."""
        a = ProxyService.getInstance()
        b = ProxyService.getInstance()
        assert a is b

    def test_initializeWithoutLifecycle(self):
        """Config without lifecycle section creates no ProxyLifecycle."""
        svc = ProxyService.getInstance()
        proxyConfigDict = cast(ProxyConfigDict, {"enabled": False, "type": "http", "address": ""})

        svc.initialize(proxyConfigDict)

        assert len(svc._activeLifecycles) == 0

    def test_initializeWithLifecycle(self):
        """Config with lifecycle section creates ProxyLifecycle and calls start()."""
        svc = ProxyService.getInstance()
        proxyConfigDict = cast(
            ProxyConfigDict,
            {
                "enabled": True,
                "type": "socks5",
                "address": "socks5://127.0.0.1:1080",
                "lifecycle": {
                    "start-command": ["echo", "start"],
                    "stop-command": ["echo", "stop"],
                    "health-check-type": "none",
                },
            },
        )

        with patch("internal.services.proxy.service.asyncio.run") as mockRun:
            svc.initialize(proxyConfigDict)

        assert "global" in svc._activeLifecycles
        mockRun.assert_called_once()  # start() called via asyncio.run()

    def test_resolveProxyDelegates(self):
        """resolveProxy() returns same result as ProxyConfig.fromServiceConfig()."""
        svc = ProxyService.getInstance()

        serviceConfig = {"use-proxy": True, "proxy": {"enabled": True, "type": "http", "address": "http://p:8080"}}

        result = svc.resolveProxy(serviceConfig, "test-svc")
        expected = ProxyConfig.fromServiceConfig(serviceConfig)

        assert result.type == expected.type
        assert result.address == expected.address
        assert result.enabled == expected.enabled
        assert len(svc._activeLifecycles) == 0  # No lifecycle section

    def test_resolveProxyWithLifecycle(self):
        """Service config with lifecycle creates a ProxyLifecycle (deferred start)."""
        svc = ProxyService.getInstance()

        serviceConfig = {
            "use-proxy": True,
            "proxy": {
                "enabled": True,
                "type": "socks5",
                "address": "socks5://127.0.0.1:1081",
                "lifecycle": {
                    "start-command": ["ssh"],
                    "stop-command": ["pkill"],
                    "health-check-type": "none",
                },
            },
        }

        result = svc.resolveProxy(serviceConfig, "test-svc")

        assert "test-svc" in svc._activeLifecycles
        lifecycle = svc._activeLifecycles["test-svc"]
        assert lifecycle.label == "test-svc"
        assert lifecycle._started is False  # Not started yet (deferred)
        assert result.type == "socks5"

    def test_resolveProxyDeduplicates(self):
        """Calling resolveProxy() twice with same label creates only one lifecycle."""
        svc = ProxyService.getInstance()

        serviceConfig = {
            "use-proxy": True,
            "proxy": {
                "enabled": True,
                "type": "http",
                "address": "http://p:8080",
                "lifecycle": {"start-command": ["cmd"], "health-check-type": "none"},
            },
        }

        svc.resolveProxy(serviceConfig, "test-svc")
        assert len(svc._activeLifecycles) == 1

        svc.resolveProxy(serviceConfig, "test-svc")
        assert len(svc._activeLifecycles) == 1

    @pytest.mark.asyncio
    async def test_dtCronJobDelegates(self):
        """_dtCronJob delegates to each lifecycle's onCronTick()."""
        svc = ProxyService.getInstance()
        mockLifecycle1 = MagicMock()
        mockLifecycle1.started = True
        mockLifecycle1.onCronTick = AsyncMock()
        mockLifecycle2 = MagicMock()
        mockLifecycle2.started = True
        mockLifecycle2.onCronTick = AsyncMock()

        svc._activeLifecycles = {"a": mockLifecycle1, "b": mockLifecycle2}

        mockTask = MagicMock()
        await svc._dtCronJob(mockTask)

        mockLifecycle1.onCronTick.assert_called_once()
        mockLifecycle2.onCronTick.assert_called_once()

    @pytest.mark.asyncio
    async def test_dtCronJobStartsDeferred(self):
        """On first tick, deferred lifecycles get started."""
        svc = ProxyService.getInstance()
        mockLifecycle = MagicMock()
        mockLifecycle.started = False
        mockLifecycle.start = AsyncMock()
        mockLifecycle.onCronTick = AsyncMock()

        svc._activeLifecycles = {"deferred": mockLifecycle}

        mockTask = MagicMock()
        await svc._dtCronJob(mockTask)

        mockLifecycle.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_dtOnExitDelegates(self):
        """_dtOnExit delegates to each lifecycle's onExit() and clears registry."""
        svc = ProxyService.getInstance()
        mockLifecycle = MagicMock()
        mockLifecycle.onExit = AsyncMock()

        svc._activeLifecycles = {"a": mockLifecycle}

        mockTask = MagicMock()
        await svc._dtOnExit(mockTask)

        mockLifecycle.onExit.assert_called_once()
        assert len(svc._activeLifecycles) == 0

    def test_initializeDisabledWithLifecycle(self):
        """Config with enabled=false and lifecycle section creates no ProxyLifecycle."""
        svc = ProxyService.getInstance()
        proxyConfigDict = cast(
            ProxyConfigDict,
            {
                "enabled": False,  # Kill-switch OFF
                "type": "socks5",
                "address": "socks5://127.0.0.1:1080",
                "lifecycle": {
                    "start-command": ["ssh"],
                    "health-check-type": "none",
                },
            },
        )

        with patch("internal.services.proxy.service.asyncio.run") as mockRun:
            svc.initialize(proxyConfigDict)

        assert len(svc._activeLifecycles) == 0
        mockRun.assert_not_called()  # No asyncio.run() because lifecycle wasn't created

    def test_resolveProxyDisabledNoLifecycle(self):
        """Service with use-proxy=false and lifecycle creates no ProxyLifecycle."""
        svc = ProxyService.getInstance()
        svc._activeLifecycles = {}

        serviceConfig = {
            "use-proxy": False,  # Proxy disabled for this service
            "proxy": {
                "enabled": True,
                "type": "socks5",
                "address": "socks5://127.0.0.1:1081",
                "lifecycle": {
                    "start-command": ["ssh"],
                    "health-check-type": "none",
                },
            },
        }

        with patch("internal.services.proxy.service.asyncio.run") as mockRun:
            result = svc.resolveProxy(serviceConfig, "disabled-svc")

        assert len(svc._activeLifecycles) == 0
        mockRun.assert_not_called()
        assert result.type == "none"  # fromServiceConfig with useProxy=False returns NONE
