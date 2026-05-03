"""Cache models for the cache service.

This module defines enums and data structures used throughout the cache service
to manage cache persistence behavior and namespace organization. It provides
type-safe definitions for cache entry persistence levels and predefined cache
namespaces with automatic persistence level determination.

The module uses Python's Enum and StrEnum to create type-safe, self-documenting
enumerations that integrate seamlessly with the cache service architecture.
"""

from enum import Enum, StrEnum


class CachePersistenceLevel(Enum):
    """Persistence behavior for cache entries.

    This enum defines how cache entries should be persisted to storage,
    allowing the cache service to optimize performance based on data
    criticality and access patterns.

    Attributes:
        MEMORY_ONLY: Cache entries are never persisted to storage and exist
            only in memory. Used for ephemeral data like database query results
            that can be reconstructed on demand.
        ON_CHANGE: Cache entries are persisted immediately upon any modification.
            Used for critical data that must survive service crashes.
        ON_SHUTDOWN: Cache entries are persisted when the service stops gracefully.
            Used for data that should survive restarts but doesn't require
            immediate persistence guarantees.
    """

    MEMORY_ONLY = "memory"  # Never persisted (e.g., DB Cache)
    ON_CHANGE = "on_change"  # Persisted immediately (critical data)
    ON_SHUTDOWN = "on_shutdown"  # Persisted when service stops


class CacheNamespace(StrEnum):
    """Predefined cache namespaces with their persistence rules.

    This enum defines logical groupings for cache entries, allowing the cache
    service to organize data by type and apply appropriate persistence strategies.
    Each namespace automatically determines its persistence level based on
    the data's importance and reconstruction cost.

    Attributes:
        CHATS: Namespace for ephemeral chat-related data that exists only in
            memory. Used for temporary chat state and session data.
        CHAT_PERSISTENT: Namespace for chat data that should persist across
            service restarts. Uses ON_SHUTDOWN persistence level.
        CHAT_USERS: Namespace for user data within chat contexts. Exists only
            in memory and can be reconstructed from the database.
        USERS: Namespace for user profile and preference data. Uses ON_SHUTDOWN
            persistence level to survive service restarts.
    """

    CHATS = "chats"
    CHAT_PERSISTENT = "chatPersistent"
    CHAT_USERS = "chatUsers"
    USERS = "users"

    def getPersistenceLevel(self) -> CachePersistenceLevel:
        """Auto-determine persistence level based on namespace.

        This method provides automatic persistence level assignment for each
        namespace, ensuring consistent behavior without manual configuration.
        Critical user data uses ON_SHUTDOWN persistence, while ephemeral
        data uses MEMORY_ONLY.

        Returns:
            CachePersistenceLevel: The persistence level appropriate for this
                namespace. Returns ON_SHUTDOWN for USERS and CHAT_PERSISTENT
                namespaces, MEMORY_ONLY for all others.

        Examples:
            >>> CacheNamespace.USERS.getPersistenceLevel()
            <CachePersistenceLevel.ON_SHUTDOWN: 'on_shutdown'>
            >>> CacheNamespace.CHATS.getPersistenceLevel()
            <CachePersistenceLevel.MEMORY_ONLY: 'memory'>
        """
        match self:
            case CacheNamespace.USERS | CacheNamespace.CHAT_PERSISTENT:
                return CachePersistenceLevel.ON_SHUTDOWN
            case _:
                return CachePersistenceLevel.MEMORY_ONLY

    @property
    def value(self) -> str:
        """Get string value of namespace.

        This property provides access to the underlying string value of the
        enum member, which is used as the actual namespace key in cache storage.

        Returns:
            str: The string representation of this namespace (e.g., 'chats',
                'users', 'chatPersistent', 'chatUsers').

        Examples:
            >>> CacheNamespace.CHATS.value
            'chats'
            >>> CacheNamespace.USERS.value
            'users'
        """
        return self._value_
