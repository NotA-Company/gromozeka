"""Common functions repository module for database operations.

This module provides the CommonFunctionsRepository class that implements
common utility functions for managing configuration settings in the database.
These functions allow storing and retrieving key-value configuration settings
that can be used across the application.
"""

import logging
from typing import Dict, Optional

from ..manager import DatabaseManager
from .base import BaseRepository

logger = logging.getLogger(__name__)


class CommonFunctionsRepository(BaseRepository):
    """Repository for common database utility functions.

    Provides methods for managing configuration settings stored in the database.
    Settings are stored as key-value pairs and can be used for application-wide
    configuration that needs to persist across restarts.
    """

    __slots__ = ()
    """Restricts instance attributes to prevent dynamic attribute creation."""

    def __init__(self, manager: DatabaseManager):
        """Initialize the common functions repository.

        Args:
            manager: DatabaseManager instance for accessing database providers
                    and executing database operations
        """
        super().__init__(manager)

    ###
    # Global Settings manipulation functions (Are they used an all?)
    ###

    async def setSetting(self, key: str, value: str, *, dataSource: Optional[str] = None) -> bool:
        """
        Set a configuration setting.

        Args:
            key: Setting key
            value: Setting value
            dataSource: Optional data source name for explicit routing

        Returns:
            bool: True if successful, False otherwise

        Note:
            Writes to default source. Cannot write to readonly sources.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=False)

            await sqlProvider.execute(
                """
                    INSERT OR REPLACE INTO settings
                    (key, value, updated_at)
                    VALUES (:key, :value, CURRENT_TIMESTAMP)
                """,
                {
                    "key": key,
                    "value": value,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set setting {key} in {dataSource}: {e}")
            return False

    async def getSetting(
        self, key: str, default: Optional[str] = None, *, dataSource: Optional[str] = None
    ) -> Optional[str]:
        """Get a configuration setting.

        Args:
            key: Setting key to retrieve
            default: Default value if key not found
            dataSource: Optional data source name

        Returns:
            Setting value or default if not found"""
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)

            row = await sqlProvider.executeFetchOne("SELECT value FROM settings WHERE key = ?", (key,))
            return row["value"] if row else default
        except Exception as e:
            logger.error(f"Failed to get setting {key} in {dataSource}: {e}")
            return default

    async def getSettings(self, *, dataSource: Optional[str] = None) -> Dict[str, str]:
        """Get all configuration settings.

        Args:
            dataSource: Optional data source name

        Returns:
            Dictionary of all key-value settings"""
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
            ret = await sqlProvider.executeFetchAll("SELECT * FROM settings")
            return {row["key"]: row["value"] for row in ret}
        except Exception as e:
            logger.error(f"Failed to get settings in {dataSource}: {e}")
            return {}
