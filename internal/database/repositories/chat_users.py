"""Repository for managing chat users in the database.

This module provides the ChatUsersRepository class which handles CRUD operations
for chat users, including storing/updating user information, retrieving user data,
and querying users across chats. Supports multi-source database routing and
aggregation.
"""

import datetime
import logging
from collections.abc import MutableSet
from typing import List, Optional

from telegram import Chat

from .. import utils as dbUtils
from ..manager import DatabaseManager
from ..models import ChatInfoDict, ChatUserDict
from ..providers.base import ExcludedValue
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ChatUsersRepository(BaseRepository):
    """Repository for managing chat users in the database.

    Provides methods to store, update, and retrieve user information within chats.
    Supports multi-source database routing with automatic aggregation and deduplication.
    """

    __slots__ = ()  # No additional instance variables beyond base class

    def __init__(self, manager: DatabaseManager):
        """Initialize the chat users repository.

        Args:
            manager: DatabaseManager instance for database operations and routing
        """
        super().__init__(manager)

    ###
    # Chat Users manipulation functions
    ###

    async def updateChatUser(self, chatId: int, userId: int, username: str, fullName: str) -> bool:
        """Store or update a user as a chat member with their current information.

        This method performs an upsert operation on the chat_users table. If the user
        is not already a member of the chat, they will be added. If they already exist,
        their @username, full_name, and updated_at timestamp will be refreshed.

        Args:
            chatId: The unique identifier of the chat (used for source routing)
            userId: The unique identifier of the user
            username: The current @username of the user (may be None) (Note: Should be with @ sign)
            fullName: The current full name/display name of the user

        Returns:
            bool: True if the operation succeeded, False if an exception occurred

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
            The updated_at timestamp is automatically set to current timestamp
            on both insert and update operations.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.upsert(
                table="chat_users",
                values={
                    "chat_id": chatId,
                    "user_id": userId,
                    "username": username,
                    "full_name": fullName,
                    "updated_at": dbUtils.getCurrentTimestamp(),
                    "created_at": dbUtils.getCurrentTimestamp(),
                },
                conflictColumns=["chat_id", "user_id"],
                updateExpressions={
                    "username": ExcludedValue(),
                    "full_name": ExcludedValue(),
                    "updated_at": ExcludedValue(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update username for user {userId} in chat {chatId}: {e}")
            return False

    async def getChatUser(
        self, chatId: int, userId: int, *, dataSource: Optional[str] = None
    ) -> Optional[ChatUserDict]:
        """Get user information for a specific user in a chat.

        Args:
            chatId: Chat identifier
            userId: User identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            ChatUserDict containing user information or None if not found
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            row = await sqlProvider.executeFetchOne(
                """
                SELECT * FROM chat_users
                WHERE
                    chat_id = :chatId
                    AND user_id = :userId
                LIMIT 1
            """,
                {
                    "chatId": chatId,
                    "userId": userId,
                },
            )
            return dbUtils.sqlToTypedDict(row, ChatUserDict) if row else None
        except Exception as e:
            logger.error(f"Failed to get user {userId} in chat {chatId}: {e}")
            return None

    async def updateUserMetadata(self, chatId: int, userId: int, metadata: str) -> bool:
        """
        Update metadata for a chat user.

        Args:
            chatId: Chat identifier (used for source routing)
            userId: User identifier
            metadata: Metadata string

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                UPDATE chat_users
                SET metadata = :metadata,
                    updated_at = :updatedAt
                WHERE
                    chat_id = :chatId
                    AND user_id = :userId
            """,
                {
                    "chatId": chatId,
                    "userId": userId,
                    "metadata": metadata,
                    "updatedAt": dbUtils.getCurrentTimestamp(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update metadata for user {userId} in chat {chatId}: {e}")
            return False

    async def getChatUserByUsername(
        self,
        chatId: int,
        username: str,
        *,
        dataSource: Optional[str] = None,
    ) -> Optional[ChatUserDict]:
        """Get user information by username within a specific chat.

        Args:
            chatId: Chat identifier
            username: Username to search for (exact match)
            dataSource: Optional data source name for explicit routing

        Returns:
            ChatUserDict containing user information or None if not found
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            caseInsensitiveComparison = sqlProvider.getCaseInsensitiveComparison("username", "username")
            row = await sqlProvider.executeFetchOne(
                f"""
                SELECT * FROM chat_users
                WHERE
                    chat_id = :chatId
                    AND {caseInsensitiveComparison}
                LIMIT 1
            """,
                {
                    "chatId": chatId,
                    "username": username,
                },
            )
            return dbUtils.sqlToTypedDict(row, ChatUserDict) if row else None
        except Exception as e:
            logger.error(f"Failed to get user {username} in chat {chatId}: {e}")
            return None

    async def getChatUsers(
        self,
        chatId: int,
        limit: int = 10,
        seenSince: Optional[datetime.datetime] = None,
        *,
        dataSource: Optional[str] = None,
    ) -> List[ChatUserDict]:
        """
        Get the usernames of all users in a chat,
        optionally filtered by when they last sent a message.

        Args:
            chatId: The chat ID to get users from
            limit: Maximum number of users to return
            seenSince: Optional datetime to filter users by last message time
            dataSource: Optional data source identifier for multi-source database routing

        Returns:
            List of ChatUserDict objects representing users in the chat
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT * FROM chat_users
                WHERE
                    chat_id = :chatId
                    AND (:seenSince IS NULL OR updated_at > :seenSince)
                ORDER BY updated_at DESC
                LIMIT :limit
            """,
                {
                    "chatId": chatId,
                    "limit": limit,
                    "seenSince": seenSince,
                },
            )

            return [dbUtils.sqlToTypedDict(row, ChatUserDict) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get users for chat {chatId}: {e}")
            return []

    async def getUserChats(self, userId: int, *, dataSource: Optional[str] = None) -> List[ChatInfoDict]:
        """
        Get chats user was seen in.

        Args:
            userId: User identifier
            dataSource: Optional data source name. If None in multi-source mode,
                       aggregates from all sources and deduplicates by (userId, chatId).

        Returns:
            List of ChatInfoDict
        """

        # Multi-source aggregation
        logger.debug(f"Aggregating getUserChats for user {userId} from sources, dood!")
        allResults: List[ChatInfoDict] = []
        seen: MutableSet[int] = set()  # Deduplicate by (userId, chatId)

        sourcesList = [dataSource] if dataSource else self.manager._providers.keys()

        for sourceName in sourcesList:
            try:
                sqlProvider = await self.manager.getProvider(dataSource=sourceName, readonly=True)
                rows = await sqlProvider.executeFetchAll(
                    """
                    SELECT ci.* FROM chat_info ci
                    JOIN chat_users cu ON cu.chat_id = ci.chat_id
                    WHERE
                        user_id = :userId
                """,
                    {
                        "userId": userId,
                    },
                )
                for row in rows:
                    chatInfo = dbUtils.sqlToTypedDict(row, ChatInfoDict)
                    key = chatInfo["chat_id"]
                    if key not in seen:
                        seen.add(key)
                        allResults.append(chatInfo)
            except Exception as e:
                logger.warning(f"Failed to get chats from source '{sourceName}': {e}, dood!")
                continue

        logger.debug(f"Aggregated {len(allResults)} unique chats for user {userId}, dood!")
        return allResults

    async def getAllGroupChats(self, *, dataSource: Optional[str] = None) -> List[ChatInfoDict]:
        """
        Get all group chats.

        Args:
            dataSource: Optional data source name. If None in multi-source mode,
                       aggregates from all sources and deduplicates by chatId.

        Returns:
            List of ChatInfoDict
        """
        # Multi-source aggregation
        logger.debug("Aggregating getAllGroupChats from sources, dood!")
        allResults: List[ChatInfoDict] = []
        seen: MutableSet[int] = set()  # Deduplicate by chatId

        sourcesList = [dataSource] if dataSource else self.manager._providers.keys()
        for sourceName in sourcesList:
            try:
                sqlProvider = await self.manager.getProvider(dataSource=sourceName, readonly=True)
                rows = await sqlProvider.executeFetchAll(
                    """
                    SELECT ci.* FROM chat_info ci
                    WHERE
                        type in (:groupChat, :supergroupChat)
                """,
                    {
                        "groupChat": Chat.GROUP,
                        "supergroupChat": Chat.SUPERGROUP,
                    },
                )
                for row in rows:
                    chatInfo = dbUtils.sqlToTypedDict(row, ChatInfoDict)
                    chatId = chatInfo["chat_id"]
                    if chatId not in seen:
                        seen.add(chatId)
                        allResults.append(chatInfo)
            except Exception as e:
                logger.warning(f"Failed to get group chats from source '{sourceName}': {e}, dood!")
                continue

        logger.debug(f"Aggregated {len(allResults)} unique group chats, dood!")
        return allResults

    async def getUserIdByUserName(self, username: str, *, dataSource: Optional[str] = None) -> List[int]:
        """
        Get all user IDs associated with a username across data sources.

        Performs case-insensitive username lookup in chat_info table. Aggregates
        results from all sources by default or queries specific source if provided.

        Args:
            username: Username to search for (case-insensitive)
            dataSource: Optional specific data source name. If None, aggregates from all sources.

        Returns:
            List of unique user IDs matching the username. Empty list if not found.
        """

        # Multi-source aggregation
        logger.debug(f"Aggregating userId for username {username} from sources, dood!")
        resultSet: MutableSet[int] = set[int]()

        sourcesList = [dataSource] if dataSource else self.manager._providers.keys()

        for sourceName in sourcesList:
            try:
                sqlProvider = await self.manager.getProvider(dataSource=sourceName, readonly=True)
                rows = await sqlProvider.executeFetchAll(
                    """
                    SELECT chat_id FROM chat_info
                    WHERE
                        LOWER(username) = :username
                """,
                    {
                        "username": username.lower(),
                    },
                )
                for row in rows:
                    resultSet.add(dict(row)["chat_id"])
            except Exception as e:
                logger.warning(f"Failed to get info from source '{sourceName}': {e}, dood!")
                continue

        logger.debug(f"Aggregated {len(resultSet)} unique user_id's for user {username}, dood!")
        return list(resultSet)
