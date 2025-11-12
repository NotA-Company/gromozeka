import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from .interface import RateLimiterInterface

logger = logging.getLogger(__name__)


@dataclass
class QueueConfig:
    """
    Configuration for rate limiting.

    This config applies to all queues managed by a single
    SlidingWindowRateLimiter instance.

    Attributes:
        maxRequests: Maximum requests allowed within the time window
        windowSeconds: Time window duration in seconds
    """

    maxRequests: int
    windowSeconds: int

    def __post_init__(self):
        """Validate configuration values"""
        if self.maxRequests <= 0:
            raise ValueError("maxRequests must be positive")
        if self.windowSeconds <= 0:
            raise ValueError("windowSeconds must be positive")


class SlidingWindowRateLimiter(RateLimiterInterface):
    """
    Sliding window rate limiter implementation.

    This implementation uses a sliding window algorithm to track
    request timestamps and enforce rate limits. All queues managed
    by this instance share the same rate limit configuration.

    To have different rate limits for different queues, create
    multiple SlidingWindowRateLimiter instances with different
    configs and register them with the manager.

    Algorithm:
        1. Remove timestamps outside the current time window
        2. Check if remaining requests exceed the limit
        3. If limit exceeded, calculate wait time and sleep
        4. Add current request timestamp

    Thread Safety:
        Uses asyncio.Lock per queue for thread-safe operations
        in concurrent async environments.

    Example:
        >>> # Create limiter for API calls (20 req/min)
        >>> apiLimiter = SlidingWindowRateLimiter(
        ...     QueueConfig(maxRequests=20, windowSeconds=60)
        ... )
        >>> await apiLimiter.initialize()
        >>>
        >>> # Create limiter for DB operations (100 req/min)
        >>> dbLimiter = SlidingWindowRateLimiter(
        ...     QueueConfig(maxRequests=100, windowSeconds=60)
        ... )
        >>> await dbLimiter.initialize()
        >>>
        >>> # Register with manager
        >>> manager = RateLimiterManager.getInstance()
        >>> manager.registerRateLimiter("api", apiLimiter)
        >>> manager.registerRateLimiter("database", dbLimiter)
        >>> manager.bindQueue("yandex_search", "api")
        >>> manager.bindQueue("postgres", "database")
    """

    def __init__(self, config: QueueConfig):
        """
        Initialize the sliding window rate limiter.

        Args:
            config: Rate limit configuration to apply to all queues
        """
        self._config = config
        self._requestTimes: Dict[str, List[float]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize the rate limiter.

        Sets up internal state. Queues are registered dynamically
        on first use.
        """
        if self._initialized:
            logger.warning("SlidingWindowRateLimiter already initialized")
            return

        self._initialized = True
        logger.info(
            f"SlidingWindowRateLimiter initialized with "
            f"{self._config.maxRequests} requests per "
            f"{self._config.windowSeconds} seconds, dood!"
        )

    async def destroy(self) -> None:
        """
        Clean up rate limiter resources.

        Clears all tracking data and resets state.
        """
        self._requestTimes.clear()
        self._locks.clear()
        self._initialized = False
        logger.info("SlidingWindowRateLimiter destroyed, dood!")

    def _ensureQueue(self, queue: str) -> None:
        """
        Ensure queue is registered (internal helper).

        Args:
            queue: Queue name to ensure exists
        """
        if queue not in self._requestTimes:
            self._requestTimes[queue] = []
            self._locks[queue] = asyncio.Lock()
            logger.debug(f"Auto-registered queue '{queue}', dood!")

    async def applyLimit(self, queue: str = "default") -> None:
        """
        Apply rate limiting for the specified queue.

        This method implements the sliding window algorithm:
        1. Auto-registers queue if needed
        2. Removes old timestamps outside the window
        3. Checks if limit is exceeded
        4. Sleeps if necessary to respect the limit
        5. Records the current request timestamp

        Args:
            queue: Name of the queue to apply rate limiting to.
                   Auto-registered on first use.

        Example:
            >>> await limiter.applyLimit("api")  # May sleep if limit exceeded
            >>> await limiter.applyLimit("other_api")  # Different queue, same limits
        """
        # Auto-register queue on first use
        self._ensureQueue(queue)

        async with self._locks[queue]:
            currentTime = time.time()

            # Remove old request times outside the window
            self._requestTimes[queue] = [
                reqTime for reqTime in self._requestTimes[queue] if currentTime - reqTime < self._config.windowSeconds
            ]

            # Check if we've exceeded the rate limit
            if len(self._requestTimes[queue]) >= self._config.maxRequests:
                # Calculate how long to wait
                oldestRequest = min(self._requestTimes[queue])
                waitTime = self._config.windowSeconds - (currentTime - oldestRequest)

                if waitTime > 0:
                    logger.debug(f"Rate limit reached for queue '{queue}', " f"waiting {waitTime:.2f} seconds, dood!")
                    await asyncio.sleep(waitTime)

                    # Clean up old requests after waiting
                    currentTime = time.time()
                    self._requestTimes[queue] = [
                        reqTime
                        for reqTime in self._requestTimes[queue]
                        if currentTime - reqTime < self._config.windowSeconds
                    ]

            # Add current request time
            self._requestTimes[queue].append(currentTime)

    def getStats(self, queue: str = "default") -> Dict[str, Any]:
        """
        Get current rate limiting statistics for a queue.

        Args:
            queue: Name of the queue to get statistics for

        Returns:
            Dictionary containing:
            - requestsInWindow: Current requests in the time window
            - maxRequests: Maximum allowed requests per window
            - windowSeconds: Time window duration in seconds
            - resetTime: Unix timestamp when window will reset
            - utilizationPercent: Percentage of limit used (0-100)

        Raises:
            ValueError: If the queue doesn't exist

        Example:
            >>> stats = limiter.getStats("api")
            >>> print(f"Using {stats['utilizationPercent']:.1f}% of rate limit")
        """
        if queue not in self._requestTimes:
            raise ValueError(f"Queue '{queue}' does not exist")

        currentTime = time.time()

        # Get recent requests within the window
        recentRequests = [
            reqTime for reqTime in self._requestTimes[queue] if currentTime - reqTime < self._config.windowSeconds
        ]

        requestsInWindow = len(recentRequests)
        utilizationPercent = (requestsInWindow / self._config.maxRequests) * 100

        return {
            "requestsInWindow": requestsInWindow,
            "maxRequests": self._config.maxRequests,
            "windowSeconds": self._config.windowSeconds,
            "resetTime": max(recentRequests) + self._config.windowSeconds if recentRequests else currentTime,
            "utilizationPercent": utilizationPercent,
        }

    def listQueues(self) -> List[str]:
        """
        Get list of all known queues.

        Returns:
            List of queue names that have been used

        Example:
            >>> limiter.listQueues()
            ['default', 'api_endpoint_1', 'api_endpoint_2']
        """
        return list(self._requestTimes.keys())
