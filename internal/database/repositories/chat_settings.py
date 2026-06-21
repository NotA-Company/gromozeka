"""Chat settings repository module for database operations.

This module provides the ChatSettingsRepository class for managing chat-specific
settings in the database. It handles CRUD operations for chat settings including
setting, unsetting, clearing, and retrieving settings for individual chats.
"""

import logging
from typing import Any, Dict, Optional

from ..manager import DatabaseManager
from ..providers.base import ExcludedValue
from ..utils import getCurrentTimestamp
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ChatSettingsRepository(BaseRepository):
    """Repository for managing chat-specific settings in the database.

    Provides methods to set, unset, clear, and retrieve settings for individual
    chats. All write operations are routed based on chatId mapping to the
    appropriate data source. Settings are stored as key-value pairs with
    tracking of which user last updated each setting.
    """

    __slots__ = ()

    def __init__(self, manager: DatabaseManager):
        """Initialize the chat settings repository with a database manager.

        Args:
            manager: DatabaseManager instance for accessing database providers
                    and executing database operations
        """
        super().__init__(manager)

    ###
    # Chat Settings manipulation (see chat_settings.py for more details)
    ###

    async def setChatSetting(self, chatId: int, key: str, value: Any, *, updatedBy: int) -> bool:
        """
        Set a setting for a chat.

        Args:
            chatId: Chat identifier (used for source routing)
            key: Setting key
            value: Setting value
            updatedBy: User ID who updated the setting (default: 0)

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.upsert(
                table="chat_settings",
                values={
                    "chat_id": chatId,
                    "key": key,
                    "value": value,
                    "updated_by": updatedBy,
                    "updated_at": getCurrentTimestamp(),
                    "created_at": getCurrentTimestamp(),
                },
                conflictColumns=["chat_id", "key"],
                updateExpressions={
                    "value": ExcludedValue(),
                    "updated_by": ExcludedValue(),
                    "updated_at": ExcludedValue(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set setting {key} for chat {chatId}: {e}")
            return False

    async def unsetChatSetting(self, chatId: int, key: str) -> bool:
        """
        Unset a setting for a chat.

        Args:
            chatId: Chat identifier (used for source routing)
            key: Setting key to remove

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes are routed based on chatId mapping. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, readonly=False)
            await sqlProvider.execute(
                """
                DELETE FROM chat_settings
                WHERE chat_id = :chatId
                    AND key = :key
            """,
                {
                    "chatId": chatId,
                    "key": key,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to unset setting {key} for chat {chatId}: {e}")
            return False

    async def clearChatSettings(self, chatId: int) -> bool:
        """
        Clear all settings for a chat.

        Args:
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
                DELETE FROM chat_settings
                WHERE chat_id = :chatId
            """,
                {"chatId": chatId},
            )
            return True
        except Exception as e:
            logger.error(f"Failed to clear settings for chat {chatId}: {e}")
            return False

    async def getChatSetting(self, chatId: int, setting: str, *, dataSource: Optional[str] = None) -> Optional[str]:
        """
        Get a setting for a chat.

        Args:
            chatId: Chat identifier
            setting: Setting key to retrieve
            dataSource: Optional data source name for explicit routing

        Returns:
            Optional[str]: Setting value or None if not found
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            row = await sqlProvider.executeFetchOne(
                """
                SELECT value FROM chat_settings
                WHERE
                    chat_id = :chatId
                    AND key = :key
                LIMIT 1
            """,
                {"chatId": chatId, "key": setting},
            )
            return row["value"] if row else None
        except Exception as e:
            logger.error(f"Failed to get setting {setting} for chat {chatId}: {e}")
            return None

    async def getChatSettings(self, chatId: int, *, dataSource: Optional[str] = None) -> Dict[str, tuple[str, int]]:
        """
        Get all settings for a chat.

        Args:
            chatId: Chat identifier
            dataSource: Optional data source name for explicit routing

        Returns:
            Dict mapping setting keys to tuples with value and updated_by values
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            rows = await sqlProvider.executeFetchAll(
                """
                SELECT key, value, updated_by FROM chat_settings
                WHERE chat_id = :chatId
            """,
                {"chatId": chatId},
            )
            return {row["key"]: (row["value"], row["updated_by"]) for row in rows}
        except Exception as e:
            logger.error(f"Failed to get settings for chat {chatId}: {e}")
            return {}

    async def listChatsBySetting(
        self,
        key: str,
        *,
        dataSource: Optional[str] = None,
    ) -> Dict[int, str]:
        """List all ``(chat_id, value)`` rows whose ``key`` setting is present.

        Used by ``ChatSearchHandler._dtCronJob`` to discover chats with
        ``REGENERATE_EMBEDDINGS=true`` / ``EMBEDDINGS_ENABLED=true`` —
        callers do the value filtering in Python via
        :meth:`ChatSettingsValue.toBool` so the comparison stays
        case-insensitive (``"true"``, ``"True"``, ``"TRUE"``, ``"1"``
        all match the truthy check) and lives next to the rest of the
        codebase's settings parsing. Returning both columns (instead of
        just chat IDs) lets the caller re-parse the stored value with
        the same `ChatSettingsValue` helper it uses everywhere else,
        instead of relying on a SQL-level exact match that would silently
        drop chats whose setting was written in a different case.

        Aggregates across all **configured** data sources in multi-source
        mode (sources that have not been accessed since startup are still
        queried — ``getProvider`` lazily initializes each one) and
        deduplicates by ``chat_id``.

        Args:
            key: Setting key to match (e.g. ``"regenerate-embeddings"``).
            dataSource: Optional data source name. When provided, only that
                source is queried. When ``None``, every configured provider
                is consulted and the results are unioned.

        Returns:
            Dict[chatId, value]
        """
        # logger.debug(f"Listing chats with setting {key} (dataSource={dataSource})")
        allResults: Dict[int, str] = {}
        # Iterate over *configured* sources, not just the ones that have
        # been lazily initialised so far.
        sourcesList = [dataSource] if dataSource else self.manager._providers.keys()

        for sourceName in sourcesList:
            try:
                sqlProvider = await self.manager.getProvider(dataSource=sourceName, readonly=True)
                rows = await sqlProvider.executeFetchAll(
                    """
                    SELECT chat_id, value FROM chat_settings
                    WHERE key = :key
                """,
                    {"key": key},
                )
                for row in rows:
                    chatId = row.get("chat_id")
                    rowValue = row.get("value")
                    if chatId is None or rowValue is None:
                        logger.debug(f"Skipping row with missing chat_id or value: {row}")
                        continue
                    # First-write-wins on duplicates across sources; the
                    # stored value is the same in both (settings are
                    # per-chat, not per-source), so this only matters when
                    # two sources both have a row for the same chat — in
                    # which case either is correct.
                    allResults.setdefault(chatId, rowValue)
            except Exception as e:
                logger.warning(f"Failed to list chats with setting {key} from source {sourceName!r}: {e}")
                continue
        return allResults
