"""Proxy lifecycle manager for a single proxy process.

Handles start, periodic health-check, automatic restart on failure,
and graceful stop for a proxy process (e.g., an SSH SOCKS5 tunnel).
Integrates with QueueService's CRON_JOB and DO_EXIT delayed task
functions via the onCronTick() and onExit() hooks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

import httpx

from lib.proxy import HealthCheckType, ProxyConfig, ProxyLifecycleConfigDict

logger = logging.getLogger(__name__)


class ProxyLifecycle:
    """Manages the lifecycle of a single proxy process.

    Handles start, periodic health-check, automatic restart on failure,
    and graceful stop for a proxy process (e.g., an SSH SOCKS5 tunnel).
    Integrates with QueueService's CRON_JOB and DO_EXIT delayed task
    functions via the onCronTick() and onExit() hooks.

    Attributes:
        label: Human-readable label for logging (e.g. "global",
            "openweathermap").
        config: The lifecycle configuration dict (commands, health check
            settings).
        proxyConfig: The resolved proxy configuration, used for URL health
            checks.
        _starting: ``True`` while `start()` is in progress. Prevents
            concurrent `start()` calls from launching duplicate processes.
    """

    def __init__(
        self,
        label: str,
        config: ProxyLifecycleConfigDict,
        proxyConfig: ProxyConfig,
    ) -> None:
        """Initialise a proxy lifecycle manager.

        If the config has misconfigurations (e.g., URL health check without
        a URL), a warning is logged but no exception is raised. The lifecycle
        continues to function with the start/stop commands; health checks
        are silently disabled for the misconfigured type.

        Args:
            label: Human-readable label for this lifecycle instance.
            config: Lifecycle configuration with commands and health check
                settings. All fields are optional.
            proxyConfig: The resolved ProxyConfig, used for building HTTP
                clients for URL-based health checks.
        """
        self.label = label
        self.config = config
        self.proxyConfig = proxyConfig
        self._tickCounter = 0
        self._started = False
        """Whether the proxy process has been started. See :attr:`started`."""
        self._starting = False
        """Whether `start()` is currently executing. Guards against re-entrancy."""

        # Validate configuration
        self._validateConfig()

    @property
    def started(self) -> bool:
        """Whether the proxy process has been started.

        Set to ``True`` by :meth:`start` after the start command is launched
        (or when no start command is configured). Used by :class:`ProxyService`
        to avoid double-starting lifecycles.

        Returns:
            ``True`` if the proxy has been started, ``False`` otherwise.
        """
        return self._started

    def _validateConfig(self) -> None:
        """Log warnings for misconfigured lifecycle settings.

        Does not raise — misconfiguration is non-fatal. The lifecycle still
        functions for start/stop; health checks are disabled where applicable.
        """
        hcType = self.config.get("healthCheckType", HealthCheckType.NONE)
        if hcType == HealthCheckType.URL and not self.config.get("healthCheckUrl"):
            logger.warning(
                "[%s] health-check-type is 'url' but health-check-url is empty; " "health checks will be disabled.",
                self.label,
            )
        if hcType == HealthCheckType.COMMAND and not self.config.get("healthCheckCommand"):
            logger.warning(
                "[%s] health-check-type is 'command' but health-check-command is empty; "
                "health checks will be disabled.",
                self.label,
            )

    async def _runCommand(
        self, command: List[str], *, waitForCompletion: bool = False, timeout: int = 30
    ) -> Optional[int]:
        """Run a shell command via asyncio subprocess.

        Args:
            command: Command and arguments as a list of strings.
            waitForCompletion: If True, wait for the process to exit (with
                timeout). If False, fire-and-forget.
            timeout: Maximum seconds to wait when waitForCompletion is True.

        Returns:
            Exit code if waitForCompletion is True, None otherwise.
        """
        if not command:
            return None

        logger.debug("[%s] Running command: %s (wait=%s)", self.label, command, waitForCompletion)
        try:
            stdout = asyncio.subprocess.PIPE if waitForCompletion else asyncio.subprocess.DEVNULL
            stderr = asyncio.subprocess.PIPE if waitForCompletion else asyncio.subprocess.DEVNULL
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=stdout,
                stderr=stderr,
            )
            if waitForCompletion:
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                    if stdout:
                        logger.debug("[%s] stdout: %s", self.label, stdout.decode(errors="replace"))
                    if stderr:
                        logger.debug("[%s] stderr: %s", self.label, stderr.decode(errors="replace"))
                    return process.returncode
                except asyncio.TimeoutError:
                    logger.warning("[%s] Command timed out after %ds: %s", self.label, timeout, command)
                    try:
                        process.kill()
                        await process.wait()
                    except Exception:
                        pass
                    return None
            return None
        except Exception as e:
            logger.warning("[%s] Failed to run command %s: %s", self.label, command, e)
            return None

    async def _checkUrl(self, url: str) -> bool:
        """Perform a URL-based health check through the proxy.

        Makes an HTTP GET request through the configured proxy to verify
        end-to-end connectivity. Any 2xx response = healthy.

        Args:
            url: URL to probe.

        Returns:
            True if the probe succeeds (2xx), False otherwise.
        """
        try:
            proxyKwargs = self.proxyConfig.toKwargs()
            async with httpx.AsyncClient(**proxyKwargs, timeout=10.0) as client:
                response = await client.get(url)
                return 200 <= response.status_code < 300
        except Exception as e:
            logger.warning("[%s] URL health check failed (%s): %s", self.label, url, e)
            return False

    async def start(self) -> None:
        """Start the proxy process (fire-and-forget).

        The start command is launched via asyncio.create_subprocess_exec
        and not awaited — typical proxies (e.g., ssh -D ... -N) run
        indefinitely. No PID is tracked.

        Uses a ``_starting`` re-entrancy guard to prevent concurrent calls
        from launching duplicate proxy processes.
        """
        if self._started or self._starting:
            return
        self._starting = True
        try:
            startCommand = self.config.get("startCommand", [])
            if not startCommand:
                logger.debug("[%s] No start command configured; skipping.", self.label)
                self._started = True
                return
            logger.info("[%s] Starting proxy process...", self.label)
            await self._runCommand(startCommand, waitForCompletion=False)
            self._started = True
        finally:
            self._starting = False

    async def stop(self) -> None:
        """Stop the proxy process.

        Awaits the stop command with a timeout. If the stop command is
        empty, this is a no-op.
        """
        stopCommand = self.config.get("stopCommand", [])
        if not stopCommand:
            logger.debug("[%s] No stop command configured; skipping.", self.label)
            return
        logger.info("[%s] Stopping proxy process...", self.label)
        await self._runCommand(stopCommand, waitForCompletion=True)

    async def restart(self) -> None:
        """Restart the proxy process.

        If a restartCommand is configured, runs it (fire-and-forget).
        Otherwise, runs stopCommand and then startCommand sequentially.
        """
        restartCommand = self.config.get("restartCommand", [])
        if restartCommand:
            logger.warning("[%s] Restarting proxy via restart command...", self.label)
            await self._runCommand(restartCommand, waitForCompletion=False)
            return

        logger.warning("[%s] Restarting proxy via stop + start...", self.label)
        await self.stop()
        await self.start()

    async def healthCheck(self) -> bool:
        """Run a health check using the configured method.

        Dispatches to URL or command health check based on healthCheckType.
        Returns True for NONE type (no monitoring) and for validated
        misconfigurations (e.g., URL type with empty URL).

        Returns:
            True if healthy or health checks are disabled, False if unhealthy.
        """
        hcType = self.config.get("healthCheckType", HealthCheckType.NONE)

        if hcType == HealthCheckType.NONE:
            return True

        if hcType == HealthCheckType.URL:
            url = self.config.get("healthCheckUrl")
            if not url:
                return True  # Validated in __init__; treated as disabled
            return await self._checkUrl(url)

        if hcType == HealthCheckType.COMMAND:
            command = self.config.get("healthCheckCommand")
            if not command:
                return True  # Validated in __init__; treated as disabled
            exitCode = await self._runCommand(command, waitForCompletion=True)
            return exitCode == 0

        return True

    async def onCronTick(self) -> None:
        """Handle a CRON_JOB tick.

        Increments the tick counter and runs a health check if the interval
        has elapsed. Triggers restart on health check failure.
        """
        self._tickCounter += 1
        interval = self.config.get("healthCheckInterval", 5)
        if interval <= 0:
            interval = 5

        if self._tickCounter % interval != 0:
            return

        logger.debug("[%s] Running health check (tick %d)...", self.label, self._tickCounter)
        try:
            healthy = await self.healthCheck()
        except Exception as e:
            logger.warning("[%s] Health check raised an exception: %s", self.label, e)
            healthy = False

        if not healthy:
            logger.warning("[%s] Health check failed; restarting proxy.", self.label)
            try:
                await self.restart()
            except Exception as e:
                logger.error("[%s] Restart failed: %s", self.label, e)

    async def onExit(self) -> None:
        """Handle DO_EXIT (application shutdown).

        Delegates to stop() to tear down the proxy process gracefully.
        """
        logger.info("[%s] Proxy lifecycle shutting down...", self.label)
        try:
            await self.stop()
        except Exception as e:
            logger.error("[%s] Error during proxy stop on exit: %s", self.label, e)
