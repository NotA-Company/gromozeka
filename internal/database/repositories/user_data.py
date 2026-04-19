"""TODO: write docstring"""

import logging
from typing import Dict, Optional

from ..manager import DatabaseManager
from .base import BaseRepository

logger = logging.getLogger(__name__)


class UserDataRepository(BaseRepository):
    """TODO: write docstring"""

    __slots__ = ()

    def __init__(self, manager: DatabaseManager):
        super().__init__(manager)

    ###
    # User Data manipulation functions
    ###

    async def addUserData(self, userId: int, chatId: int, key: str, data: str) -> bool:
        """
        Add user knowledge to the database.

        Args:
            userId: User identifier
            chatId: Chat identifier (used for source routing)
            key: Data key
            data: Data value

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                INSERT INTO user_data
                    (user_id, chat_id, key, data)
                VALUES
                    (:userId, :chatId, :key, :data)
                ON CONFLICT DO UPDATE SET
                    data = :data,
                    updated_at = CURRENT_TIMESTAMP
            """,
                {
                    "userId": userId,
                    "chatId": chatId,
                    "key": key,
                    "data": data,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add user knowledge: {e}")
            return False

    async def getUserData(self, userId: int, chatId: int, *, dataSource: Optional[str] = None) -> Dict[str, str]:
        """
        Get user knowledge from the database.

        Args:
            userId: User identifier
            chatId: Chat identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            Dictionary mapping keys to data values
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
        """
        Delete specific user data.

        Args:
            userId: User identifier
            chatId: Chat identifier (used for source routing)
            key: Data key to delete

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
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
        """
        Clear all user data in chat.

        Args:
            userId: User identifier
            chatId: Chat identifier (used for source routing)

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
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
