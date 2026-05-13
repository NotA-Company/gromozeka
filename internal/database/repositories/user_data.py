"""User data repository module for database operations.

This module provides the UserDataRepository class for managing user-specific
data storage and retrieval. It handles CRUD operations for user data entries
that are keyed by user ID, chat ID, and data key, supporting the bot's
knowledge management and user context persistence features.

Example:
    >>> from internal.database.manager import DatabaseManager
    >>> from internal.database.repositories.user_data import UserDataRepository
    >>>
    >>> manager = DatabaseManager()
    >>> repo = UserDataRepository(manager)
    >>>
    >>> # Add user data
    >>> await repo.addUserData(userId=123, chatId=456, key="preference", data="dark_mode")
    >>>
    >>> # Retrieve user data
    >>> data = await repo.getUserData(userId=123, chatId=456)
    >>> print(data)  # {'preference': 'dark_mode'}
    >>>
    >>> # Delete specific data
    >>> await repo.deleteUserData(userId=123, chatId=456, key="preference")
    >>>
    >>> # Clear all user data
    >>> await repo.clearUserData(userId=123, chatId=456)
"""

import logging
from typing import Dict, Optional

from ..manager import DatabaseManager
from ..providers.base import ExcludedValue
from ..utils import getCurrentTimestamp
from .base import BaseRepository

logger = logging.getLogger(__name__)


class UserDataRepository(BaseRepository):
    """Repository for managing user data in the database.

    Provides methods to add, retrieve, delete, and clear user-specific data
    entries. User data is stored with a composite key of user_id, chat_id,
    and key, allowing for context-aware data storage across different
    conversations and users.

    Attributes:
        Inherits all attributes from BaseRepository, including:
        - manager: DatabaseManager instance for database operations

    Example:
        >>> repo = UserDataRepository(databaseManager)
        >>> await repo.addUserData(123, 456, "theme", "dark")
    """

    __slots__ = ()
    """Restricts instance attributes to only those inherited from BaseRepository."""

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the user data repository with a database manager.

        Args:
            manager: DatabaseManager instance for accessing database providers
                    and executing database operations

        Raises:
            TypeError: If manager is not a DatabaseManager instance
        """
        super().__init__(manager)

    ###
    # User Data manipulation functions
    ###

    async def addUserData(self, userId: int, chatId: int, key: str, data: str) -> bool:
        """Add user knowledge to the database.

        Performs an upsert operation to insert or update user data. If a record
        with the same user_id, chat_id, and key exists, it will be updated with
        the new data value and timestamp.

        Args:
            userId: User identifier (Telegram user ID)
            chatId: Chat identifier (used for source routing)
            key: Data key (e.g., "preference", "context", "state")
            data: Data value to store (string representation)

        Returns:
            bool: True if the operation completed successfully, False otherwise

        Raises:
            Exception: If database operation fails (caught and logged, returns False)

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
            The operation uses upsert with conflict resolution on (user_id, chat_id, key).
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.upsert(
                table="user_data",
                values={
                    "user_id": userId,
                    "chat_id": chatId,
                    "key": key,
                    "data": data,
                    "updated_at": getCurrentTimestamp(),
                    "created_at": getCurrentTimestamp(),
                },
                conflictColumns=["user_id", "chat_id", "key"],
                updateExpressions={
                    "data": ExcludedValue(),
                    "updated_at": ExcludedValue(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add user knowledge: {e}")
            return False

    async def getUserData(self, userId: int, chatId: int, *, dataSource: Optional[str] = None) -> Dict[str, str]:
        """Get user knowledge from the database.

        Retrieves all data entries for a specific user in a specific chat.
        Returns a dictionary mapping data keys to their corresponding values.

        Args:
            userId: User identifier (Telegram user ID)
            chatId: Chat identifier
            dataSource: Optional data source name for explicit routing. If not provided,
                       routing is determined by chatId mapping.

        Returns:
            Dict[str, str]: Dictionary mapping data keys to their string values.
                          Returns empty dict if no data found or on error.

        Raises:
            Exception: If database operation fails (caught and logged, returns empty dict)
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT * FROM user_data
                WHERE
                    user_id = :userId AND chat_id = :chatId
            """,
                {
                    "userId": userId,
                    "chatId": chatId,
                },
            )
            return {row["key"]: row["data"] for row in rows}
        except Exception as e:
            logger.error(f"Failed to get user knowledge: {e}")
            return {}

    async def deleteUserData(self, userId: int, chatId: int, key: str) -> bool:
        """Delete specific user data.

        Removes a single data entry identified by the composite key of
        user_id, chat_id, and key.

        Args:
            userId: User identifier (Telegram user ID)
            chatId: Chat identifier (used for source routing)
            key: Data key to delete (e.g., "preference", "context")

        Returns:
            bool: True if the deletion completed successfully, False otherwise

        Raises:
            Exception: If database operation fails (caught and logged, returns False)

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
            If the specified key does not exist, the operation still returns True.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                DELETE FROM user_data
                WHERE chat_id = :chatId AND
                    user_id = :userId AND
                    key = :key
                """,
                {
                    "chatId": chatId,
                    "userId": userId,
                    "key": key,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete user {chatId}:{userId} data {key}: {e}")
            return False

    async def clearUserData(self, userId: int, chatId: int) -> bool:
        """Clear all user data in chat.

        Removes all data entries for a specific user in a specific chat.
        This is useful for resetting user context or clearing conversation history.

        Args:
            userId: User identifier (Telegram user ID)
            chatId: Chat identifier (used for source routing)

        Returns:
            bool: True if the clear operation completed successfully, False otherwise

        Raises:
            Exception: If database operation fails (caught and logged, returns False)

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
            This operation deletes all keys for the specified user/chat combination.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                DELETE FROM user_data
                WHERE chat_id = :chatId AND
                    user_id = :userId
                """,
                {
                    "chatId": chatId,
                    "userId": userId,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to clear user {chatId}:{userId} data: {e}")
            return False
