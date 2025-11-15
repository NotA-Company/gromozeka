from lib.rate_limiter import RateLimiterManager


async def initRateLimiter(limiterName: str = "default", slow: bool = False) -> RateLimiterManager:
    """
    Initialize a rate limiter for testing purposes.

    This function creates and configures a sliding window rate limiter with the specified
    name and configuration. It uses the singleton RateLimiterManager to ensure the rate
    limiter persists across all tests. If a rate limiter with the given name already exists,
    it returns the existing manager without creating a new one.

    Args:
        limiterName: Name of the rate limiter to create or retrieve. Defaults to "default".
        slow: If True, creates a rate limiter with very restrictive limits (1 request/second)
              for testing rate limiting behavior. If False, creates a permissive rate limiter
              (1000 requests/second) for normal testing. Defaults to False.

    Returns:
        RateLimiterManager: The singleton rate limiter manager instance with the configured
                          rate limiter registered.

    Example:
        >>> # Create a permissive rate limiter for normal testing
        >>> manager = await initRateLimiter("test_api", slow=False)
        >>> # Create a restrictive rate limiter for testing rate limiting behavior
        >>> manager = await initRateLimiter("test_slow", slow=True)
    """
    manager = RateLimiterManager.getInstance()
    # As it's singleton, it preserved across all tests, so we need to check if
    # This rate limiter isn't present yet
    if limiterName not in manager.listRateLimiters():
        await manager.loadConfig(
            {
                "ratelimiters": {
                    limiterName: {
                        "type": "SlidingWindow",
                        "config": {
                            "maxRequests": 1 if slow else 1000,
                            "windowSeconds": 1,
                        },
                    },
                },
            }
        )
    return manager
