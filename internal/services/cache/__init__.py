"""
Cache module: Centralized caching service for Gromozeka bot
"""

from .models import CacheNamespace, CachePersistenceLevel
from .service import CacheService, LRUCache
from .types import (
    HandlersCacheDict,
    HCChatAdminsDict,
    HCChatCacheDict,
    HCChatPersistentCacheDict,
    HCChatUserCacheDict,
    HCSpamWarningMessageInfo,
    HCUserCacheDict,
    UserActiveActionEnum,
    UserActiveConfigurationDict,
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
    "HCChatAdminsDict",
    "HCChatPersistentCacheDict",
    "HCChatUserCacheDict",
    "HCSpamWarningMessageInfo",
    "HCUserCacheDict",
    "HandlersCacheDict",
    "UserActiveActionEnum",
    "UserActiveConfigurationDict",
    "UserDataType",
    "UserDataValueType",
]
