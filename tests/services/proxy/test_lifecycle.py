"""Unit tests for ProxyLifecycle class."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from internal.services.proxy.lifecycle import ProxyLifecycle
from lib.proxy import (
    HealthCheckType,
    ProxyConfig,
    ProxyLifecycleConfigDict,
    ProxyType,
)


class TestProxyLifecycle:
    """Unit tests for ProxyLifecycle."""

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _makeConfig(self, **overrides: Any) -> ProxyLifecycleConfigDict:
        """Create a lifecycle config with sensible defaults for testing.

        Args:
            **overrides: Lifecycle config fields to override defaults.

        Returns:
            A ProxyLifecycleConfigDict with defaults that can be overridden.
        """
        defaults: Dict[str, Any] = {
            "startCommand": ["echo", "start"],
            "stopCommand": ["echo", "stop"],
            "healthCheckType": HealthCheckType.NONE,
            "healthCheckInterval": 5,
        }
        defaults.update(overrides)
        return cast(ProxyLifecycleConfigDict, defaults)

    def _makeProxyConfig(self, **overrides: Any) -> ProxyConfig:
        """Create a ProxyConfig with sensible defaults for testing.

        Args:
            **overrides: ProxyConfig fields to override defaults.

        Returns:
            A ProxyConfig instance configured for HTTP proxying.
        """
        return ProxyConfig(
            proxyType=ProxyType.HTTP,  # pyright: ignore[reportArgumentType]
            address="http://proxy:8080",
            **overrides,
        )

    # ------------------------------------------------------------------ #
    #  start()
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_startRunsStartCommand(self):
        """start() runs the start command fire-and-forget."""
        lifecycle = ProxyLifecycle("test", self._makeConfig(), self._makeProxyConfig())

        with patch("internal.services.proxy.lifecycle.asyncio.create_subprocess_exec") as mockCreate:
            mockProcess = AsyncMock()
            mockCreate.return_value = mockProcess

            await lifecycle.start()

            mockCreate.assert_called_once_with(
                "echo", "start", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            # Fire-and-forget: communicate() must NOT be awaited
            mockProcess.communicate.assert_not_called()

    @pytest.mark.asyncio
    async def test_startEmptyCommand(self):
        """Empty startCommand is a no-op, no subprocess created."""
        lifecycle = ProxyLifecycle("test", self._makeConfig(startCommand=[]), self._makeProxyConfig())

        with patch("internal.services.proxy.lifecycle.asyncio.create_subprocess_exec") as mockCreate:
            await lifecycle.start()
            mockCreate.assert_not_called()

    # ------------------------------------------------------------------ #
    #  stop()
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_stopWaitsForCompletion(self):
        """stop() awaits the stop command and returns its exit code."""
        lifecycle = ProxyLifecycle("test", self._makeConfig(), self._makeProxyConfig())

        with patch("internal.services.proxy.lifecycle.asyncio.create_subprocess_exec") as mockCreate:
            mockProcess = AsyncMock()
            mockProcess.communicate = AsyncMock(return_value=(b"out", b"err"))
            mockProcess.returncode = 0
            mockCreate.return_value = mockProcess

            await lifecycle.stop()

            mockCreate.assert_called_once_with(
                "echo", "stop", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            mockProcess.communicate.assert_called_once()

    @pytest.mark.asyncio
    async def test_stopEmptyCommand(self):
        """Empty stopCommand is a no-op, no subprocess created."""
        lifecycle = ProxyLifecycle("test", self._makeConfig(stopCommand=[]), self._makeProxyConfig())

        with patch("internal.services.proxy.lifecycle.asyncio.create_subprocess_exec") as mockCreate:
            await lifecycle.stop()
            mockCreate.assert_not_called()

    @pytest.mark.asyncio
    async def test_stopTimeout(self):
        """stop() logs warning on timeout and returns without exception."""
        lifecycle = ProxyLifecycle("test", self._makeConfig(), self._makeProxyConfig())

        with (
            patch("internal.services.proxy.lifecycle.asyncio.create_subprocess_exec") as mockCreate,
            patch(
                "internal.services.proxy.lifecycle.asyncio.wait_for",
                side_effect=asyncio.TimeoutError,
            ),
        ):
            mockProcess = AsyncMock()
            # kill() is synchronous on real asyncio.subprocess.Process
            mockProcess.kill = MagicMock()
            mockCreate.return_value = mockProcess

            # Must not raise despite TimeoutError
            await lifecycle.stop()
            mockProcess.kill.assert_called_once()
            mockCreate.assert_called_once()

    # ------------------------------------------------------------------ #
    #  restart()
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_restartUsesRestartCommand(self):
        """When restartCommand is set, it is called instead of stop+start."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(restartCommand=["restart", "cmd"]),
            self._makeProxyConfig(),
        )

        with patch("internal.services.proxy.lifecycle.asyncio.create_subprocess_exec") as mockCreate:
            mockProcess = AsyncMock()
            mockCreate.return_value = mockProcess

            await lifecycle.restart()

            # Only restart command should be called, not stop or start
            mockCreate.assert_called_once_with(
                "restart",
                "cmd",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

    @pytest.mark.asyncio
    async def test_restartFallsBackToStopStart(self):
        """When restartCommand is empty, stop then start are called."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(restartCommand=[]),
            self._makeProxyConfig(),
        )

        with patch("internal.services.proxy.lifecycle.asyncio.create_subprocess_exec") as mockCreate:
            # Process for stop (waited for completion)
            mockProcessStop = AsyncMock()
            mockProcessStop.communicate = AsyncMock(return_value=(b"", b""))
            mockProcessStop.returncode = 0

            # Process for start (fire-and-forget — not awaited further)
            mockProcessStart = AsyncMock()

            mockCreate.side_effect = [mockProcessStop, mockProcessStart]

            await lifecycle.restart()

            # Should call stop command (waited) then start command (fire-and-forget)
            assert mockCreate.call_count == 2
            # First call: stop command
            args1, kwargs1 = mockCreate.call_args_list[0]
            assert args1 == ("echo", "stop")
            # Second call: start command
            args2, kwargs2 = mockCreate.call_args_list[1]
            assert args2 == ("echo", "start")

    # ------------------------------------------------------------------ #
    #  healthCheck() — NONE
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_healthCheckNone(self):
        """healthCheckType NONE always returns True (no-op)."""
        lifecycle = ProxyLifecycle(
            "test", self._makeConfig(healthCheckType=HealthCheckType.NONE), self._makeProxyConfig()
        )

        result = await lifecycle.healthCheck()
        assert result is True

    # ------------------------------------------------------------------ #
    #  healthCheck() — URL
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    @patch.object(ProxyConfig, "toKwargs", return_value={})
    @patch("internal.services.proxy.lifecycle.httpx.AsyncClient")
    async def test_healthCheckUrl2xx(self, mockHttpx, mockToKwargs):
        """URL health check returns True on 2xx response."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.URL,
                healthCheckUrl="http://example.com/health",
            ),
            self._makeProxyConfig(),
        )

        mockClient = AsyncMock()
        mockResponse = AsyncMock()
        mockResponse.status_code = 200
        mockClient.get = AsyncMock(return_value=mockResponse)
        mockHttpx.return_value.__aenter__.return_value = mockClient

        result = await lifecycle.healthCheck()

        assert result is True
        mockClient.get.assert_called_once_with("http://example.com/health")

    @pytest.mark.asyncio
    @patch.object(ProxyConfig, "toKwargs", return_value={})
    @patch("internal.services.proxy.lifecycle.httpx.AsyncClient")
    async def test_healthCheckUrl5xx(self, mockHttpx, mockToKwargs):
        """URL health check returns False on 5xx response."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.URL,
                healthCheckUrl="http://example.com/health",
            ),
            self._makeProxyConfig(),
        )

        mockClient = AsyncMock()
        mockResponse = AsyncMock()
        mockResponse.status_code = 503
        mockClient.get = AsyncMock(return_value=mockResponse)
        mockHttpx.return_value.__aenter__.return_value = mockClient

        result = await lifecycle.healthCheck()

        assert result is False

    @pytest.mark.asyncio
    @patch.object(ProxyConfig, "toKwargs", return_value={})
    @patch("internal.services.proxy.lifecycle.httpx.AsyncClient")
    async def test_healthCheckUrlException(self, mockHttpx, mockToKwargs):
        """URL health check returns False on network exception."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.URL,
                healthCheckUrl="http://example.com/health",
            ),
            self._makeProxyConfig(),
        )

        mockClient = AsyncMock()
        mockClient.get = AsyncMock(side_effect=Exception("Connection refused"))
        mockHttpx.return_value.__aenter__.return_value = mockClient

        result = await lifecycle.healthCheck()

        assert result is False

    @pytest.mark.asyncio
    @patch.object(ProxyConfig, "toKwargs", return_value={})
    @patch("internal.services.proxy.lifecycle.httpx.AsyncClient")
    async def test_healthCheckUrlMisconfigured(self, mockHttpx, mockToKwargs):
        """URL type with empty URL returns True (treated as disabled)."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.URL,
                healthCheckUrl="",
            ),
            self._makeProxyConfig(),
        )

        result = await lifecycle.healthCheck()
        assert result is True
        mockHttpx.assert_not_called()

    # ------------------------------------------------------------------ #
    #  healthCheck() — COMMAND
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_healthCheckCommand0(self):
        """Command health check returns True on exit code 0."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.COMMAND,
                healthCheckCommand=["check", "health"],
            ),
            self._makeProxyConfig(),
        )

        with patch("internal.services.proxy.lifecycle.asyncio.create_subprocess_exec") as mockCreate:
            mockProcess = AsyncMock()
            mockProcess.communicate = AsyncMock(return_value=(b"", b""))
            mockProcess.returncode = 0
            mockCreate.return_value = mockProcess

            result = await lifecycle.healthCheck()

            assert result is True
            mockCreate.assert_called_once_with(
                "check",
                "health",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

    @pytest.mark.asyncio
    async def test_healthCheckCommandNonZero(self):
        """Command health check returns False on non-zero exit code."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.COMMAND,
                healthCheckCommand=["check", "health"],
            ),
            self._makeProxyConfig(),
        )

        with patch("internal.services.proxy.lifecycle.asyncio.create_subprocess_exec") as mockCreate:
            mockProcess = AsyncMock()
            mockProcess.communicate = AsyncMock(return_value=(b"", b""))
            mockProcess.returncode = 1
            mockCreate.return_value = mockProcess

            result = await lifecycle.healthCheck()

            assert result is False

    @pytest.mark.asyncio
    async def test_healthCheckCommandMisconfigured(self):
        """COMMAND type with empty command returns True (treated as disabled)."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.COMMAND,
                healthCheckCommand=[],
            ),
            self._makeProxyConfig(),
        )

        with patch("internal.services.proxy.lifecycle.asyncio.create_subprocess_exec") as mockCreate:
            result = await lifecycle.healthCheck()
            assert result is True
            mockCreate.assert_not_called()

    @pytest.mark.asyncio
    async def test_healthCheckCommandException(self):
        """Command health check returns False when subprocess creation fails."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.COMMAND,
                healthCheckCommand=["check", "health"],
            ),
            self._makeProxyConfig(),
        )

        with patch(
            "internal.services.proxy.lifecycle.asyncio.create_subprocess_exec",
            side_effect=Exception("Subprocess error"),
        ):
            result = await lifecycle.healthCheck()
            assert result is False

    # ------------------------------------------------------------------ #
    #  onCronTick()
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_onCronTickGating(self):
        """onCronTick() skips health check until interval elapses."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.COMMAND,
                healthCheckCommand=["check"],
                healthCheckInterval=3,
            ),
            self._makeProxyConfig(),
        )

        with patch.object(lifecycle, "healthCheck", AsyncMock(return_value=True)) as mockHc:
            # Ticks 1, 2: skip (1%3 != 0, 2%3 != 0)
            await lifecycle.onCronTick()
            await lifecycle.onCronTick()
            assert lifecycle._tickCounter == 2
            mockHc.assert_not_called()

            # Tick 3: health check runs (3%3 == 0)
            await lifecycle.onCronTick()
            assert lifecycle._tickCounter == 3
            mockHc.assert_called_once()

    @pytest.mark.asyncio
    async def test_onCronTickRestartsOnFailure(self):
        """onCronTick() calls restart() when health check fails."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.COMMAND,
                healthCheckCommand=["check"],
                healthCheckInterval=1,
            ),
            self._makeProxyConfig(),
        )

        with (
            patch.object(lifecycle, "healthCheck", AsyncMock(return_value=False)) as mockHc,
            patch.object(lifecycle, "restart", AsyncMock()) as mockRestart,
        ):
            await lifecycle.onCronTick()

            mockHc.assert_called_once()
            mockRestart.assert_called_once()

    @pytest.mark.asyncio
    async def test_onCronTickHealthCheckException(self):
        """onCronTick() catches health check exception and restarts."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.COMMAND,
                healthCheckCommand=["check"],
                healthCheckInterval=1,
            ),
            self._makeProxyConfig(),
        )

        with (
            patch.object(lifecycle, "healthCheck", AsyncMock(side_effect=Exception("HC crash"))) as mockHc,
            patch.object(lifecycle, "restart", AsyncMock()) as mockRestart,
        ):
            # Must not propagate the exception
            await lifecycle.onCronTick()

            mockHc.assert_called_once()
            mockRestart.assert_called_once()

    @pytest.mark.asyncio
    async def test_onCronTickRestartException(self):
        """onCronTick() catches restart exception and does not propagate."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.COMMAND,
                healthCheckCommand=["check"],
                healthCheckInterval=1,
            ),
            self._makeProxyConfig(),
        )

        with (
            patch.object(lifecycle, "healthCheck", AsyncMock(return_value=False)) as mockHc,
            patch.object(lifecycle, "restart", AsyncMock(side_effect=Exception("Restart crash"))) as mockRestart,
        ):
            # Must not propagate the exception
            await lifecycle.onCronTick()

            mockHc.assert_called_once()
            mockRestart.assert_called_once()

    @pytest.mark.asyncio
    async def test_onCronTickIntervalZeroEdgeCase(self):
        """Interval <= 0 is clamped to 5, health check only fires every 5 ticks."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.COMMAND,
                healthCheckCommand=["check"],
                healthCheckInterval=0,
            ),
            self._makeProxyConfig(),
        )

        with patch.object(lifecycle, "_runCommand", AsyncMock(return_value=0)) as mockRun:
            # Ticks 1-4: clamped interval=5, so 1%5..4%5 != 0 → skip
            for _ in range(4):
                await lifecycle.onCronTick()
            mockRun.assert_not_called()
            assert lifecycle._tickCounter == 4

            # Tick 5: 5%5 == 0 → health check runs
            await lifecycle.onCronTick()
            assert lifecycle._tickCounter == 5
            mockRun.assert_called_once()

    @pytest.mark.asyncio
    async def test_onCronTickIntervalNegativeEdgeCase(self):
        """Negative interval is clamped to 5 just like zero."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.COMMAND,
                healthCheckCommand=["check"],
                healthCheckInterval=-3,
            ),
            self._makeProxyConfig(),
        )

        with patch.object(lifecycle, "_runCommand", AsyncMock(return_value=0)) as mockRun:
            # 4 ticks: skip
            for _ in range(4):
                await lifecycle.onCronTick()
            mockRun.assert_not_called()

            # Tick 5: health check runs
            await lifecycle.onCronTick()
            mockRun.assert_called_once()

    # ------------------------------------------------------------------ #
    #  onExit()
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_onExitCallsStop(self):
        """onExit() calls stop()."""
        lifecycle = ProxyLifecycle("test", self._makeConfig(), self._makeProxyConfig())

        with patch.object(lifecycle, "stop", AsyncMock()) as mockStop:
            await lifecycle.onExit()
            mockStop.assert_called_once()

    @pytest.mark.asyncio
    async def test_onExitStopException(self):
        """onExit() catches stop() exception and does not propagate."""
        lifecycle = ProxyLifecycle("test", self._makeConfig(), self._makeProxyConfig())

        with patch.object(lifecycle, "stop", AsyncMock(side_effect=Exception("Stop crash"))):
            # Must not propagate
            await lifecycle.onExit()

    # ------------------------------------------------------------------ #
    #  __init__ validation
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_initValidatesUrlTypeWithoutUrl(self):
        """URL type without URL logs warning but does not raise."""
        # Should not raise
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.URL,
                healthCheckUrl="",
            ),
            self._makeProxyConfig(),
        )
        # Health check should return True (disabled)
        assert await lifecycle.healthCheck() is True

    @pytest.mark.asyncio
    async def test_initValidatesCommandTypeWithoutCommand(self):
        """COMMAND type without command logs warning but does not raise."""
        lifecycle = ProxyLifecycle(
            "test",
            self._makeConfig(
                healthCheckType=HealthCheckType.COMMAND,
                healthCheckCommand=[],
            ),
            self._makeProxyConfig(),
        )
        assert await lifecycle.healthCheck() is True

    # ------------------------------------------------------------------ #
    #  _runCommand edge cases
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    async def test_runCommandEmptyReturnsNone(self):
        """_runCommand with empty command list returns None."""
        lifecycle = ProxyLifecycle("test", self._makeConfig(), self._makeProxyConfig())
        result = await lifecycle._runCommand([], waitForCompletion=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_runCommandSubprocessException(self):
        """_runCommand handles subprocess creation exception gracefully."""
        lifecycle = ProxyLifecycle("test", self._makeConfig(), self._makeProxyConfig())

        with patch(
            "internal.services.proxy.lifecycle.asyncio.create_subprocess_exec",
            side_effect=Exception("Permission denied"),
        ):
            result = await lifecycle._runCommand(["some", "cmd"], waitForCompletion=True)
            assert result is None

    @pytest.mark.asyncio
    async def test_runCommandFireAndForgetReturnsNone(self):
        """_runCommand with waitForCompletion=False returns None."""
        lifecycle = ProxyLifecycle("test", self._makeConfig(), self._makeProxyConfig())

        with patch("internal.services.proxy.lifecycle.asyncio.create_subprocess_exec") as mockCreate:
            mockProcess = AsyncMock()
            mockCreate.return_value = mockProcess

            result = await lifecycle._runCommand(["some", "cmd"], waitForCompletion=False)
            assert result is None
            # Process created but communicate not called
            mockProcess.communicate.assert_not_called()
