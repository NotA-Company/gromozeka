"""TODO"""

import sys
from typing import Any, Dict, NotRequired

if sys.version_info >= (3, 14): 
    from typing import TypedDict 
else: 
    from typing_extensions import TypedDict 

class RateLimiterConfig(TypedDict):
    """TODO"""

    type: str
    config: Dict[str, Any]


class RateLimiterManagerConfig(TypedDict, closed=False):
    """TODO"""

    ratelimiters: NotRequired[Dict[str, RateLimiterConfig]]
    queues: NotRequired[Dict[str, str]]
