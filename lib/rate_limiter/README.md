# Rate Limiter Library

A reusable, thread-safe rate limiting library for the Gromozeka project that supports multiple independent queues with different rate limiter backends through a powerful singleton manager, dood!

## Features

- **Multiple Queue Support**: Manage independent rate limits for different queues
- **Flexible Backends**: Use different rate limiter instances with different configurations
- **Singleton Manager**: Global access point with queue-to-limiter mapping
- **Auto-Registration**: Queues are automatically created on first use
- **Thread Safety**: Safe for concurrent async operations
- **Comprehensive Statistics**: Monitor rate limit utilization and reset times
- **Clean Interface**: Easy to extend with new rate limiting algorithms

## Quick Start

### Basic Usage with Single Rate Limiter

```python
from lib.rate_limiter import (
    RateLimiterManager,
    SlidingWindowRateLimiter,
    QueueConfig
)

# Initialize at application startup
async def initializeRateLimiter():
    manager = RateLimiterManager.getInstance()
    
    # Create a single rate limiter (20 requests per minute)
    limiter = SlidingWindowRateLimiter(
        QueueConfig(maxRequests=20, windowSeconds=60)
    )
    await limiter.initialize()
    
    # Register it (becomes default automatically)
    manager.registerRateLimiter("default", limiter)

# Use anywhere in the application
async def makeApiCall():
    manager = RateLimiterManager.getInstance()
    await manager.applyLimit("api_endpoint_1")  # Auto-registered, uses default limiter
    # ... make API call ...
```

### Advanced Usage with Multiple Rate Limiters

```python
from lib.rate_limiter import (
    RateLimiterManager,
    SlidingWindowRateLimiter,
    QueueConfig
)

async def setupAdvancedRateLimiting():
    manager = RateLimiterManager.getInstance()
    
    # Create rate limiter for external APIs (strict limits)
    apiLimiter = SlidingWindowRateLimiter(
        QueueConfig(maxRequests=20, windowSeconds=60)
    )
    await apiLimiter.initialize()
    
    # Create rate limiter for database (higher limits)
    dbLimiter = SlidingWindowRateLimiter(
        QueueConfig(maxRequests=100, windowSeconds=60)
    )
    await dbLimiter.initialize()
    
    # Create rate limiter for cache (very high limits)
    cacheLimiter = SlidingWindowRateLimiter(
        QueueConfig(maxRequests=1000, windowSeconds=60)
    )
    await cacheLimiter.initialize()
    
    # Register all limiters
    manager.registerRateLimiter("api", apiLimiter)
    manager.registerRateLimiter("database", dbLimiter)
    manager.registerRateLimiter("cache", cacheLimiter)
    
    # Set default
    manager.setDefaultLimiter("api")
    
    # Bind specific queues
    manager.bindQueue("yandex_search", "api")
    manager.bindQueue("openweather", "api")
    manager.bindQueue("postgres_queries", "database")
    manager.bindQueue("redis_operations", "cache")
    
    # Check configuration
    print(f"Rate limiters: {manager.listRateLimiters()}")
    print(f"Queue mappings: {manager.getQueueMappings()}")
```

## API Reference

### QueueConfig

Configuration for rate limiting parameters.

```python
@dataclass
class QueueConfig:
    maxRequests: int      # Maximum requests allowed within the time window
    windowSeconds: int    # Time window duration in seconds
```

**Example:**
```python
config = QueueConfig(maxRequests=10, windowSeconds=60)  # 10 requests per minute
```

### SlidingWindowRateLimiter

Sliding window rate limiter implementation.

**Methods:**
- `async initialize()` - Initialize the rate limiter
- `async destroy()` - Clean up resources
- `async applyLimit(queue="default")` - Apply rate limiting (may sleep)
- `getStats(queue="default")` - Get statistics for a queue
- `listQueues()` - List all registered queues

**Example:**
```python
limiter = SlidingWindowRateLimiter(
    QueueConfig(maxRequests=20, windowSeconds=60)
)
await limiter.initialize()

# Apply rate limiting
await limiter.applyLimit("my_queue")

# Get statistics
stats = limiter.getStats("my_queue")
print(f"Usage: {stats['requestsInWindow']}/{stats['maxRequests']}")
print(f"Utilization: {stats['utilizationPercent']:.1f}%")
```

### RateLimiterManager

Singleton manager for multiple rate limiters with queue mapping.

**Methods:**
- `getInstance()` - Get the singleton instance
- `registerRateLimiter(name, limiter)` - Register a rate limiter
- `setDefaultLimiter(name)` - Set default rate limiter
- `bindQueue(queue, limiterName)` - Bind queue to specific limiter
- `async applyLimit(queue="default")` - Apply rate limiting
- `getStats(queue="default")` - Get statistics
- `listRateLimiters()` - List registered limiters
- `getQueueMappings()` - Get queue-to-limiter mappings
- `getDefaultLimiter()` - Get default limiter name
- `async destroy()` - Clean up all limiters

**Example:**
```python
manager = RateLimiterManager.getInstance()

# Register limiters
manager.registerRateLimiter("api", apiLimiter)
manager.registerRateLimiter("database", dbLimiter)

# Configure mappings
manager.bindQueue("yandex_search", "api")
manager.bindQueue("postgres", "database")

# Use
await manager.applyLimit("yandex_search")  # Uses API limiter
await manager.applyLimit("postgres")       # Uses database limiter
```

## Monitoring and Statistics

### Getting Statistics

```python
from lib.rate_limiter import RateLimiterManager

async def monitorRateLimits():
    manager = RateLimiterManager.getInstance()
    
    # Get all rate limiters
    for limiterName in manager.listRateLimiters():
        print(f"\nRate Limiter: {limiterName}")
        limiter = manager._rateLimiters[limiterName]
        
        # Get all queues for this limiter
        for queue in limiter.listQueues():
            stats = limiter.getStats(queue)
            print(f"  Queue: {queue}")
            print(f"    Usage: {stats['requestsInWindow']}/{stats['maxRequests']}")
            print(f"    Utilization: {stats['utilizationPercent']:.1f}%")
            print(f"    Reset time: {stats['resetTime']}")
    
    # Show queue mappings
    print(f"\nQueue Mappings: {manager.getQueueMappings()}")
    print(f"Default Limiter: {manager.getDefaultLimiter()}")
```

### Statistics Format

```python
{
    "requestsInWindow": 15,        # Current requests in time window
    "maxRequests": 20,             # Maximum allowed requests
    "windowSeconds": 60,           # Time window duration
    "resetTime": 1668336000.0,     # Unix timestamp when window resets
    "utilizationPercent": 75.0     # Percentage of limit used (0-100)
}
```

## Integration Examples

### YandexSearchClient Integration

```python
# In lib/yandex_search/client.py

from lib.rate_limiter import RateLimiterManager

class YandexSearchClient:
    def __init__(self, *, iamToken=None, apiKey=None, folderId="", 
                 requestTimeout=30, cache=None, cacheTTL=3600, 
                 useCache=True, rateLimitRequests=10, rateLimitWindow=60):
        # ... existing initialization ...
        # No need to store rate limit config or create internal limiter
        # Just use the global rate limiter manager
        # The queue will be auto-registered on first use
    
    async def _applyRateLimit(self) -> None:
        """Apply rate limiting using the global rate limiter"""
        manager = RateLimiterManager.getInstance()
        await manager.applyLimit("yandex_search")
```

### Application Startup

```python
# In main.py or application.py

from lib.rate_limiter import (
    RateLimiterManager,
    SlidingWindowRateLimiter,
    QueueConfig
)

async def initializeApplication():
    """Initialize application services including rate limiters"""
    manager = RateLimiterManager.getInstance()
    
    # Create rate limiter for Yandex Search (10 requests per minute)
    yandexLimiter = SlidingWindowRateLimiter(
        QueueConfig(maxRequests=10, windowSeconds=60)
    )
    await yandexLimiter.initialize()
    
    # Create rate limiter for OpenWeather (60 requests per minute)
    weatherLimiter = SlidingWindowRateLimiter(
        QueueConfig(maxRequests=60, windowSeconds=60)
    )
    await weatherLimiter.initialize()
    
    # Register and configure
    manager.registerRateLimiter("yandex", yandexLimiter)
    manager.registerRateLimiter("weather", weatherLimiter)
    manager.bindQueue("yandex_search", "yandex")
    manager.bindQueue("openweather", "weather")
    manager.setDefaultLimiter("yandex")
    
    print("Rate limiters initialized, dood!")

async def shutdownApplication():
    """Clean shutdown of rate limiters"""
    manager = RateLimiterManager.getInstance()
    await manager.destroy()
    print("All rate limiters destroyed, dood!")
```

## Troubleshooting

### Common Issues

**1. "No rate limiters registered" error**
```python
# Make sure to register at least one rate limiter before using
manager = RateLimiterManager.getInstance()
limiter = SlidingWindowRateLimiter(QueueConfig(maxRequests=10, windowSeconds=60))
await limiter.initialize()
manager.registerRateLimiter("default", limiter)
```

**2. "Queue does not exist" error**
```python
# Queues are auto-registered on first use, but getStats() requires
# the queue to exist. Use applyLimit() first:
await manager.applyLimit("my_queue")  # Auto-registers queue
stats = manager.getStats("my_queue")  # Now works
```

**3. Rate limiter not working**
```python
# Make sure to initialize the rate limiter
limiter = SlidingWindowRateLimiter(config)
await limiter.initialize()  # Don't forget this!
```

### Debug Logging

Enable debug logging to see rate limiting behavior:

```python
import logging
logging.getLogger("lib.rate_limiter").setLevel(logging.DEBUG)
```

### Performance Considerations

- **Memory Usage**: Each queue stores request timestamps (≈8 bytes per request)
- **Lock Contention**: Per-queue locks minimize contention
- **CPU Overhead**: Rate limiting adds < 1ms overhead per call
- **Cleanup**: Old timestamps are automatically removed on each call

## Best Practices

1. **Initialize Early**: Set up rate limiters during application startup
2. **Use Descriptive Names**: Use meaningful queue and limiter names
3. **Monitor Usage**: Regularly check statistics to tune limits
4. **Handle Shutdown**: Always call `destroy()` during application shutdown
5. **Choose Appropriate Limits**: Set limits based on API provider constraints
6. **Test Thoroughly**: Test rate limiting behavior under load

## Future Enhancements

Potential future improvements to the library:

- **Additional Algorithms**: Token bucket, leaky bucket implementations
- **Persistence**: Save/restore rate limit state across restarts
- **Distributed Limiting**: Redis-based rate limiting for multi-process scenarios
- **Dynamic Reconfiguration**: Change limits without restarting
- **Metrics Export**: Prometheus/StatsD integration
- **Rate Limit Bypass**: Testing mode to disable limits

## License

This library is part of the Gromozeka project and follows the same license terms.

---

*Remember: Rate limiting helps prevent API abuse and ensures fair usage, dood!*