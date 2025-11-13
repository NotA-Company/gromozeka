"""TODO"""

from typing import Any, Dict, NotRequired, TypedDict


class RateLimiterConfig(TypedDict):
    """TODO"""

    type: str
    config: Dict[str, Any]


class RateLimiterManagerConfig(TypedDict, closed=False):
    """TODO"""

    ratelimiters: NotRequired[Dict[str, RateLimiterConfig]]
    queues: NotRequired[Dict[str, str]]
