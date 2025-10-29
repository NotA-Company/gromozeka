"""
Cache models: Enums and data structures for cache service
"""

from enum import Enum, StrEnum


class CachePersistenceLevel(Enum):
    """Persistence behavior for cache entries"""

    MEMORY_ONLY = "memory"  # Never persisted (e.g., DB Cache)
    ON_CHANGE = "on_change"  # Persisted immediately (critical data)
    ON_SHUTDOWN = "on_shutdown"  # Persisted when service stops


class CacheNamespace(StrEnum):
    """Predefined cache namespaces with their persistence rules"""

    CHATS = "chats"
    CHAT_USERS = "chatUsers"
    USERS = "users"

    def getPersistenceLevel(self) -> CachePersistenceLevel:
        """Auto-determine persistence level based on namespace"""
        match self:
            case CacheNamespace.USERS:
                return CachePersistenceLevel.ON_SHUTDOWN
            case _:
                return CachePersistenceLevel.MEMORY_ONLY

    @property
    def value(self) -> str:
        """Get string value of namespace"""
        return self._value_
