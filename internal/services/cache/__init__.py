"""Cache module: Centralized caching service for Gromozeka bot.

This module provides a unified caching interface for the Gromozeka bot, offering
efficient data storage and retrieval with support for different persistence levels
and namespaces. It integrates with the bot's handler system to provide fast access
to frequently used data such as chat information, user data, and spam warnings.

The cache service supports:
- Multiple persistence levels (in-memory, persistent)
- Namespaced cache entries for organized data management
- LRU (Least Recently Used) eviction policy
- Type-safe cache dictionaries for different data types
- Integration with bot handlers for seamless caching

Key Components:
    CacheService: Main service class for cache operations
    LRUCache: LRU cache implementation with size limits
    CacheNamespace: Namespace definitions for cache organization
    CachePersistenceLevel: Persistence level configurations

Example:
    >>> from internal.services.cache import CacheService
    >>> cache = CacheService()
    >>> cache.set("user:123", {"name": "John"}, namespace=CacheNamespace.USER)
    >>> user_data = cache.get("user:123", namespace=CacheNamespace.USER)
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
