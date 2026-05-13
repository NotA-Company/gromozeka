"""Base repository module for database operations.

This module provides the BaseRepository abstract base class that serves as the
foundation for all repository implementations in the Gromozeka bot database layer.
Repositories are responsible for data access operations and provide a consistent
interface for working with different database providers.

The base repository pattern ensures that all concrete repositories have access
to the DatabaseManager, which handles multi-source database operations, connection
management, and provider abstraction. This design allows for flexible data access
across different database backends (SQLite, PostgreSQL, MySQL) while maintaining
a unified API for application code.

Example:
    class UserRepository(BaseRepository):
        def __init__(self, manager: DatabaseManager):
            super().__init__(manager)

        def get_user(self, user_id: int) -> Optional[User]:
            return self.manager.get_one(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
                User
            )
"""

from abc import ABC

from ..manager import DatabaseManager


class BaseRepository(ABC):
    """Abstract base class for database repositories.

    Provides the foundation for all repository implementations, ensuring they
    have access to the DatabaseManager for executing database operations across
    multiple data sources. All concrete repositories should inherit from this
    class and implement their specific data access methods.

    This base class enforces a consistent pattern for data access across the
    application, leveraging the DatabaseManager's multi-source capabilities.
    Repositories can perform read operations on any configured data source and
    write operations on the primary data source, with automatic connection
    management and transaction support.

    Attributes:
        manager: DatabaseManager instance that provides access to database
                providers and handles multi-source database operations. This
                manager abstracts the underlying database connections and
                provides methods for executing queries, managing transactions,
                and working with different database backends.

    Example:
        class MessageRepository(BaseRepository):
            def __init__(self, manager: DatabaseManager):
                super().__init__(manager)

            def get_message(self, message_id: int) -> Optional[Message]:
                return self.manager.get_one(
                    "SELECT * FROM messages WHERE id = ?",
                    (message_id,),
                    Message
                )

            def save_message(self, message: Message) -> int:
                return self.manager.execute(
                    "INSERT INTO messages (content, user_id) VALUES (?, ?)",
                    (message.content, message.user_id)
                )
    """

    __slots__ = ("manager",)
    """Restricts instance attributes to only 'manager' to prevent dynamic attribute creation.

    Using __slots__ provides memory optimization by preventing the creation of
    a __dict__ for each instance, which is beneficial for repository classes
    that may be instantiated frequently. It also helps catch typos in attribute
    assignments at runtime.
    """

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the repository with a database manager.

        Sets up the repository with access to the DatabaseManager, which provides
        the interface for all database operations. The manager handles connection
        pooling, multi-source routing, and transaction management.

        Args:
            manager: DatabaseManager instance for accessing database providers
                    and executing database operations. This manager should be
                    properly initialized with database connections before being
                    passed to the repository.

        Returns:
            None

        Raises:
            TypeError: If manager is not an instance of DatabaseManager.
        """
        self.manager = manager
