"""Proxy lifecycle management service.

Singleton service that orchestrates proxy process lifecycles across the
application. Manages ProxyLifecycle instances for the global proxy and
per-service proxy overrides, integrating with QueueService for periodic
health checks (CRON_JOB) and graceful shutdown (DO_EXIT).
"""

from __future__ import annotations

import asyncio
import logging
from threading import RLock
from typing import Dict, Optional

from internal.services.proxy.lifecycle import ProxyLifecycle
from internal.services.queue_service import DelayedTask, DelayedTaskFunction, QueueService
from lib.proxy import ProxyConfig, ProxyConfigDict, ProxyType

logger = logging.getLogger(__name__)


class ProxyService:
    """Singleton service for proxy lifecycle management.

    Manages proxy process lifecycles (start, health-check, restart, stop)
    for the global proxy and per-service proxy overrides. Integrates with
    QueueService for periodic health checks (CRON_JOB) and graceful
    shutdown (DO_EXIT).

    Usage:
        ProxyService.getInstance().initialize(proxyConfigDict)
        proxyConfig = ProxyService.getInstance().resolveProxy(serviceConfig, "my-service")

    Attributes:
        _activeLifecycles: Registry of active ProxyLifecycle instances,
            keyed by a unique label (e.g. "global", "openweathermap").
    """

    _instance: Optional["ProxyService"] = None
    _lock = RLock()

    def __new__(cls) -> "ProxyService":
        """Create or return the singleton instance.

        Returns:
            The singleton ProxyService instance.
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    @classmethod
    def getInstance(cls) -> "ProxyService":
        """Get or create the singleton ProxyService instance.

        Returns:
            The singleton ProxyService instance.
        """
        if cls._instance is None:
            return cls()
        return cls._instance

    def __init__(self) -> None:
        """Initialise the proxy service.

        Only the first call executes; subsequent calls are guarded by
        the hasattr(self, 'initialized') sentinel.
        """
        if hasattr(self, "initialized"):
            return
        self.initialized = True
        self._activeLifecycles: Dict[str, ProxyLifecycle] = {}
        self._initialized = False
        """Whether :meth:`initialize` has completed successfully.
        Prevents double-initialization."""

    def initialize(self, proxyConfigDict: ProxyConfigDict) -> None:
        """Initialise the proxy service with the global proxy configuration.

        Idempotent — subsequent calls after the first successful
        initialisation are silently skipped.

        Creates a ProxyLifecycle for the global proxy if a lifecycle
        section is present, and registers CRON_JOB and DO_EXIT handlers
        with QueueService.

        The global proxy start command is executed immediately via
        asyncio.run() because GromozekBot.__init__ runs synchronously.
        Per-service proxy lifecycles are started lazily on the first
        CRON_JOB tick.

        Args:
            proxyConfigDict: The global [proxy] config dict from
                ConfigManager.getProxyConfig().
        """
        if self._initialized:
            logger.debug("ProxyService already initialized; skipping.")
            return

        queueService = QueueService.getInstance()

        # Register delayed task handlers
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, self._dtCronJob)
        queueService.registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, self._dtOnExit)

        # Process global proxy lifecycle
        if not proxyConfigDict:
            self._initialized = True
            return

        proxyConfig = ProxyConfig.fromDict(proxyConfigDict)
        if proxyConfig.lifecycle is None or not proxyConfig.enabled:
            self._initialized = True
            return

        lifecycle = ProxyLifecycle("global", proxyConfig.lifecycle, proxyConfig)
        self._activeLifecycles["global"] = lifecycle

        # Start the global proxy immediately (sync context)
        try:
            asyncio.run(lifecycle.start())
        except Exception as e:
            logger.error("Failed to start global proxy: %s", e)

        self._initialized = True

    def resolveProxy(self, serviceConfig: Dict[str, object], serviceLabel: str) -> ProxyConfig:
        """Resolve proxy configuration for a service.

        Wraps ProxyConfig.fromServiceConfig() and creates a ProxyLifecycle
        if the service config contains a proxy.lifecycle sub-section.
        The lifecycle is deferred to the first CRON_JOB tick.

        Deduplicates by serviceLabel — calling resolveProxy() with the
        same label multiple times is safe (returns the already-resolved
        ProxyConfig without creating a duplicate lifecycle).

        Args:
            serviceConfig: Per-service config dict with optional
                ``use-proxy`` and ``proxy`` keys.
            serviceLabel: Unique label for this service's lifecycle
                (e.g. "openweathermap", "yandex-search", "telegram-bot").

        Returns:
            The resolved ProxyConfig from the service's proxy section,
            or type NONE if proxy is not enabled.
        """
        proxyConfig = ProxyConfig.fromServiceConfig(serviceConfig)

        if (
            proxyConfig.lifecycle is None
            or not proxyConfig.enabled
            or proxyConfig.type == ProxyType.NONE
            or serviceLabel in self._activeLifecycles
        ):
            return proxyConfig

        lifecycle = ProxyLifecycle(serviceLabel, proxyConfig.lifecycle, proxyConfig)
        self._activeLifecycles[serviceLabel] = lifecycle
        logger.info("[%s] Proxy lifecycle registered (will start on first cron tick).", serviceLabel)

        return proxyConfig

    async def _dtCronJob(self, task: DelayedTask) -> None:
        """Handle CRON_JOB tick.

        Starts any deferred proxy lifecycles that haven't been started yet,
        then runs health checks on all active lifecycles.

        Unlike the original one-time-startup flag, this runs the deferred
        start check on every tick. This ensures lifecycles registered via
        :meth:`resolveProxy` after the first tick (e.g. from lazy handler
        init) still get started. Already-started lifecycles are skipped
        via :attr:`ProxyLifecycle.started`.

        Args:
            task: The delayed task triggering this handler.
        """
        for label, lifecycle in list(self._activeLifecycles.items()):
            if not lifecycle.started:
                try:
                    await lifecycle.start()
                except Exception as e:
                    logger.error("[%s] Failed to start proxy: %s", label, e)

        for label, lifecycle in list(self._activeLifecycles.items()):
            try:
                await lifecycle.onCronTick()
            except Exception as e:
                logger.error("[%s] Error in proxy lifecycle cron tick: %s", label, e)

    async def _dtOnExit(self, task: DelayedTask) -> None:
        """Handle DO_EXIT (application shutdown).

        Delegates to each lifecycle's onExit() to stop proxy processes
        gracefully. Clears the active lifecycles registry after shutdown.

        Args:
            task: The delayed task triggering this handler.
        """
        logger.info("Proxy service shutting down...")
        for label, lifecycle in list(self._activeLifecycles.items()):
            try:
                await lifecycle.onExit()
            except Exception as e:
                logger.error("[%s] Error during proxy shutdown: %s", label, e)
        self._activeLifecycles.clear()
