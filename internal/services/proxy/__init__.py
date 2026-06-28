"""Proxy lifecycle management service.

Manages proxy process lifecycles — start, health-check, restart, and stop —
for the global proxy and per-service proxy overrides. Integrates with
QueueService for periodic health checks (CRON_JOB) and graceful shutdown
(DO_EXIT).
"""

from internal.services.proxy.lifecycle import ProxyLifecycle
from internal.services.proxy.service import ProxyService

__all__ = ["ProxyLifecycle", "ProxyService"]
