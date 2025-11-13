import logging
from threading import RLock
from typing import Any, Dict, List, Optional

from .interface import RateLimiterInterface
from .sliding_window import SlidingWindowRateLimiter
from .types import RateLimiterManagerConfig

logger = logging.getLogger(__name__)


class RateLimiterManager:
    """
    Singleton manager for rate limiter instances with queue-to-limiter mapping.

    This class provides a global access point to multiple rate limiters,
    allowing different queues to use different rate limiter backends.
    Follows the singleton pattern used in CacheService and QueueService.

    Architecture:
        - Manages multiple named rate limiter instances (backends)
        - Maps queues to specific rate limiters
        - Provides a default rate limiter for unmapped queues
        - Supports dynamic queue and limiter registration

    Usage:
        >>> from lib.rate_limiter import (
        ...     RateLimiterManager,
        ...     SlidingWindowRateLimiter,
        ...     QueueConfig
        ... )
        >>>
        >>> # Initialize at application startup
        >>> manager = RateLimiterManager.getInstance()
        >>>
        >>> # Create different rate limiters for different purposes
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
        >>> # Register rate limiters with names
        >>> manager.registerRateLimiter("api", apiLimiter)
        >>> manager.registerRateLimiter("database", dbLimiter)
        >>>
        >>> # Set default limiter
        >>> manager.setDefaultLimiter("api")
        >>>
        >>> # Bind specific queues to specific limiters
        >>> manager.bindQueue("yandex_search", "api")
        >>> manager.bindQueue("openweather", "api")
        >>> manager.bindQueue("postgres_queries", "database")
        >>>
        >>> # Use anywhere in the application
        >>> await manager.applyLimit("yandex_search")  # Uses api limiter
        >>> await manager.applyLimit("postgres_queries")  # Uses database limiter
        >>> await manager.applyLimit("unknown_queue")  # Uses default (api) limiter
    """

    _instance: Optional["RateLimiterManager"] = None
    _lock = RLock()

    def __new__(cls) -> "RateLimiterManager":
        """
        Create or return singleton instance with thread safety.

        Returns:
            The singleton RateLimiterManager instance
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        """
        Initialize the manager instance.

        Only runs once due to singleton pattern. Sets up:
        - Rate limiter registry (name -> instance)
        - Queue mappings (queue -> limiter name)
        - Default limiter name
        """
        if not hasattr(self, "initialized"):
            self._rateLimiters: Dict[str, RateLimiterInterface] = {}
            self._queueMappings: Dict[str, str] = {}
            self._defaultLimiter: Optional[str] = None
            self.initialized = True
            logger.info("RateLimiterManager initialized, dood!")

    @classmethod
    def getInstance(cls) -> "RateLimiterManager":
        """
        Get the singleton instance.

        Returns:
            The singleton RateLimiterManager instance
        """
        return cls()

    async def loadConfig(self, config: RateLimiterManagerConfig) -> None:
        """
        Load configuration from a dictionary.

        Args:
            config: Dictionary containing configuration data
        """

        for limiterName, limiterConfig in config.get("ratelimiters", {}).items():
            limiter: Optional[RateLimiterInterface] = None
            match limiterConfig["type"].lower():
                case "slidingwindow":
                    limiter = SlidingWindowRateLimiter(**limiterConfig["config"])
                case _:
                    raise ValueError(f"Unknown rate limiter type '{limiterConfig['type']}'")

            await limiter.initialize()
            self.registerRateLimiter(limiterName, limiter)

        for queueName, limiterName in config.get("queues", {}).items():
            self.bindQueue(queueName, limiterName)

        if "default" not in self.listRateLimiters():
            defaultLimiter = SlidingWindowRateLimiter(maxRequests=10, windowSeconds=60)
            await defaultLimiter.initialize()
            self.registerRateLimiter("default", defaultLimiter)
            logger.debug("Default rate limiter not found, using SlidingWindowRateLimiter as default, dood!")

        self.setDefaultLimiter("default")

        logger.debug("Loaded rate limiter configuration, dood!")

    def registerRateLimiter(self, name: str, limiter: RateLimiterInterface) -> None:
        """
        Register a rate limiter instance with a name.

        Args:
            name: Unique name for this rate limiter backend
            limiter: Rate limiter instance to register

        Raises:
            ValueError: If name is already registered

        Example:
            >>> apiLimiter = SlidingWindowRateLimiter(
            ...     QueueConfig(maxRequests=20, windowSeconds=60)
            ... )
            >>> await apiLimiter.initialize()
            >>> manager.registerRateLimiter("api", apiLimiter)
        """
        if name in self._rateLimiters:
            raise ValueError(f"Rate limiter '{name}' is already registered")

        self._rateLimiters[name] = limiter

        # Set as default if it's the first one
        if self._defaultLimiter is None:
            self._defaultLimiter = name
            logger.info(f"Set '{name}' as default rate limiter, dood!")

        logger.info(f"Registered rate limiter {type(limiter).__name__} with name '{name}', dood!")

    def setDefaultLimiter(self, name: str) -> None:
        """
        Set the default rate limiter to use for unmapped queues.

        Args:
            name: Name of the rate limiter to use as default

        Raises:
            ValueError: If the rate limiter name is not registered

        Example:
            >>> manager.setDefaultLimiter("api")
        """
        if name not in self._rateLimiters:
            raise ValueError(f"Rate limiter '{name}' is not registered")

        self._defaultLimiter = name
        logger.info(f"Set '{name}' as default rate limiter, dood!")

    def bindQueue(self, queue: str, limiterName: str) -> None:
        """
        Bind a queue to a specific rate limiter.

        Args:
            queue: Name of the queue to bind
            limiterName: Name of the rate limiter to use for this queue

        Raises:
            ValueError: If the rate limiter name is not registered

        Example:
            >>> manager.bindQueue("yandex_search", "api")
            >>> manager.bindQueue("postgres_queries", "database")
        """
        if limiterName not in self._rateLimiters:
            raise ValueError(f"Rate limiter '{limiterName}' is not registered")

        self._queueMappings[queue] = limiterName
        logger.info(f"Bound queue '{queue}' to rate limiter '{limiterName}', dood!")

    def _getLimiterForQueue(self, queue: str) -> RateLimiterInterface:
        """
        Get the appropriate rate limiter for a queue (internal helper).

        Args:
            queue: Queue name

        Returns:
            Rate limiter instance to use for this queue

        Raises:
            RuntimeError: If no rate limiters are registered
        """
        if not self._rateLimiters:
            raise RuntimeError("No rate limiters registered, dood!")

        # Check if queue has explicit mapping
        if queue in self._queueMappings:
            limiterName = self._queueMappings[queue]
            return self._rateLimiters[limiterName]

        # Use default limiter
        if self._defaultLimiter is None:
            raise RuntimeError("No default rate limiter set, dood!")

        return self._rateLimiters[self._defaultLimiter]

    async def applyLimit(self, queue: str = "default") -> None:
        """
        Apply rate limiting for the specified queue.

        Routes the request to the appropriate rate limiter based on
        queue mappings. Uses default limiter if queue is not mapped.

        Args:
            queue: Name of the queue to apply rate limiting to

        Raises:
            RuntimeError: If no rate limiters are registered

        Example:
            >>> await manager.applyLimit("yandex_search")  # Uses mapped limiter
            >>> await manager.applyLimit()  # Uses default limiter
        """
        limiter = self._getLimiterForQueue(queue)
        await limiter.applyLimit(queue)

    def getStats(self, queue: str = "default") -> Dict[str, Any]:
        """
        Get rate limiting statistics for a queue.

        Args:
            queue: Name of the queue to get statistics for

        Returns:
            Dictionary containing rate limit statistics

        Raises:
            RuntimeError: If no rate limiters are registered
            ValueError: If the queue doesn't exist in its limiter

        Example:
            >>> stats = manager.getStats("yandex_search")
            >>> print(f"Requests: {stats['requestsInWindow']}/{stats['maxRequests']}")
        """
        limiter = self._getLimiterForQueue(queue)
        return limiter.getStats(queue)

    def listRateLimiters(self) -> List[str]:
        """
        Get list of all registered rate limiter names.

        Returns:
            List of rate limiter names

        Example:
            >>> manager.listRateLimiters()
            ['api', 'database', 'cache']
        """
        return list(self._rateLimiters.keys())

    def getQueueMappings(self) -> Dict[str, str]:
        """
        Get all queue-to-limiter mappings.

        Returns:
            Dictionary mapping queue names to rate limiter names

        Example:
            >>> manager.getQueueMappings()
            {
                'yandex_search': 'api',
                'openweather': 'api',
                'postgres_queries': 'database'
            }
        """
        return self._queueMappings.copy()

    def getDefaultLimiter(self) -> Optional[str]:
        """
        Get the name of the default rate limiter.

        Returns:
            Name of default rate limiter, or None if not set

        Example:
            >>> manager.getDefaultLimiter()
            'api'
        """
        return self._defaultLimiter

    async def destroy(self) -> None:
        """
        Destroy all registered rate limiters and clean up.

        This method:
        1. Calls destroy() on each registered rate limiter
        2. Clears all rate limiter registrations
        3. Clears all queue mappings
        4. Resets default limiter

        Should be called during application shutdown.

        Example:
            >>> await manager.destroy()
        """
        logger.info("Destroying all rate limiters, dood!")

        # Destroy each rate limiter
        for name, limiter in self._rateLimiters.items():
            try:
                await limiter.destroy()
                logger.info(f"Destroyed rate limiter '{name}', dood!")
            except Exception as e:
                logger.error(f"Error destroying rate limiter '{name}': {e}")

        # Clear all state
        self._rateLimiters.clear()
        self._queueMappings.clear()
        self._defaultLimiter = None

        logger.info("RateLimiterManager cleanup complete, dood!")
