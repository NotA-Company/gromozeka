"""
Cache module: Centralized caching service for Gromozeka bot
"""

from .models import CacheNamespace, CachePersistenceLevel
from .service import CacheService, LRUCache
from .types import (
    HandlersCacheDict,
    HCChatCacheDict,
    HCChatPersistentCacheDict,
    HCChatUserCacheDict,
    HCSpamWarningMessageInfo,
    HCUserCacheDict,
    UserActiveActionEnum,
    UserDataType,
    UserDataValueType,
)

__all__ = [
    # Service
    "CacheService",
    "LRUCache",
    # Models
    "CachePersistenceLevel",
    "CacheNamespace",
    # Types
    "HCChatCacheDict",
    "HCChatPersistentCacheDict",
    "HCChatUserCacheDict",
    "HCSpamWarningMessageInfo",
    "HCUserCacheDict",
    "HandlersCacheDict",
    "UserActiveActionEnum",
    "UserDataType",
    "UserDataValueType",
]
