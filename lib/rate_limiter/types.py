"""Type definitions for the rate limiter library."""

import sys
from typing import Any, Dict, NotRequired

if sys.version_info >= (3, 14):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict


class RateLimiterConfig(TypedDict):
    """Configuration for a rate limiter instance.

    Attributes:
        type: The type of rate limiter (e.g., "sliding_window")
        config: Configuration parameters specific to the rate limiter type
    """

    type: str
    config: Dict[str, Any]


class RateLimiterManagerConfig(TypedDict, closed=False):
    """Configuration for the rate limiter manager.

    Attributes:
        ratelimiters: Dictionary mapping rate limiter names to their configurations
        queues: Dictionary mapping queue names to rate limiter names
    """

    ratelimiters: NotRequired[Dict[str, RateLimiterConfig]]
    queues: NotRequired[Dict[str, str]]
