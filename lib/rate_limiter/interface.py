from abc import ABC, abstractmethod
from typing import Any, Dict, List


class RateLimiterInterface(ABC):
    """
    Abstract base class for rate limiter implementations.

    All rate limiters must implement initialization, destruction,
    rate limiting application, statistics retrieval, and queue listing methods.
    Supports multiple independent queues with dynamic registration.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the rate limiter.

        This method should set up any necessary resources,
        data structures, or connections needed for rate limiting.
        Called once during setup.
        """
        pass

    @abstractmethod
    async def destroy(self) -> None:
        """
        Clean up rate limiter resources.

        This method should release any resources, close connections,
        and perform cleanup operations. Called during shutdown.
        """
        pass

    @abstractmethod
    async def applyLimit(self, queue: str = "default") -> None:
        """
        Apply rate limiting for the specified queue.

        This method blocks (sleeps) if the rate limit has been exceeded,
        ensuring that the caller respects the configured limits.
        Queues are automatically registered on first use.

        Args:
            queue: Name of the queue to apply rate limiting to.
                   Will be auto-registered if not seen before.
        """
        pass

    @abstractmethod
    def getStats(self, queue: str = "default") -> Dict[str, Any]:
        """
        Get current rate limiting statistics for a queue.

        Args:
            queue: Name of the queue to get statistics for

        Returns:
            Dictionary containing rate limit statistics:
            - requestsInWindow: Current requests in the time window
            - maxRequests: Maximum allowed requests per window
            - windowSeconds: Time window duration in seconds
            - resetTime: Unix timestamp when window will reset
            - utilizationPercent: Percentage of limit used (0-100)

        Raises:
            ValueError: If the queue doesn't exist
        """
        pass

    @abstractmethod
    def listQueues(self) -> List[str]:
        """
        Get list of all known queues managed by this rate limiter.

        Returns:
            List of queue names that have been used with this limiter

        Example:
            >>> limiter.listQueues()
            ['default', 'api', 'database']
        """
        pass
