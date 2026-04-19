"""TODO: write docstring"""

import logging
from typing import Any, Dict, Optional

from ..manager import DatabaseManager
from .base import BaseRepository

logger = logging.getLogger(__name__)


class ChatSettingsRepository(BaseRepository):
    """TODO: write docstring"""

    __slots__ = ()

    def __init__(self, manager: DatabaseManager):
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
            await sqlProvider.execute(
                """
                INSERT INTO chat_settings
                    (chat_id, key, value, updated_by, updated_at)
                VALUES
                    (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (chat_id, key)
                DO UPDATE SET
                    value = excluded.value,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
            """,
                (chatId, key, value, updatedBy),
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
                WHERE chat_id = ?
                    AND key = ?
            """,
                (chatId, key),
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
                WHERE chat_id = ?
            """,
                (chatId,),
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
            Setting value or None if not found
        """
        try:
            sqlProvider = await self.manager.getProvider(chatId=chatId, dataSource=dataSource, readonly=True)
            row = await sqlProvider.executeFetchOne(
                """
                SELECT value FROM chat_settings
                WHERE
                    chat_id = ?
                    AND key = ?
                LIMIT 1
            """,
                (chatId, setting),
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
                WHERE chat_id = ?
            """,
                (chatId,),
            )
            return {row["key"]: (row["value"], row["updated_by"]) for row in rows}
        except Exception as e:
            logger.error(f"Failed to get settings for chat {chatId}: {e}")
            return {}
