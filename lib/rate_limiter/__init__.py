"""
Rate Limiter Library

This library provides reusable rate limiting functionality with support
for multiple independent queues, different rate limiter backends per queue,
and a powerful singleton manager pattern.

Example:
    >>> from lib.rate_limiter import (
    ...     RateLimiterManager,
    ...     SlidingWindowRateLimiter,
    ...     QueueConfig
    ... )
    >>>
    >>> # Setup different rate limiters
    >>> manager = RateLimiterManager.getInstance()
    >>>
    >>> apiLimiter = SlidingWindowRateLimiter(
    ...     QueueConfig(maxRequests=20, windowSeconds=60)
    ... )
    >>> await apiLimiter.initialize()
    >>>
    >>> dbLimiter = SlidingWindowRateLimiter(
    ...     QueueConfig(maxRequests=100, windowSeconds=60)
    ... )
    >>> await dbLimiter.initialize()
    >>>
    >>> # Register and map
    >>> manager.registerRateLimiter("api", apiLimiter)
    >>> manager.registerRateLimiter("database", dbLimiter)
    >>> manager.bindQueue("yandex_search", "api")
    >>> manager.bindQueue("postgres", "database")
    >>>
    >>> # Usage
    >>> await manager.applyLimit("yandex_search")  # Uses api limiter
    >>> await manager.applyLimit("postgres")  # Uses database limiter
"""

from .interface import RateLimiterInterface
from .manager import RateLimiterManager
from .sliding_window import QueueConfig, SlidingWindowRateLimiter

__all__ = [
    "RateLimiterInterface",
    "RateLimiterManager",
    "SlidingWindowRateLimiter",
    "QueueConfig",
]
