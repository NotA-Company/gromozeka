"""Common functions repository module for database operations.

This module provides the CommonFunctionsRepository class that implements
common utility functions for managing configuration settings in the database.
These functions allow storing and retrieving key-value configuration settings
that can be used across the application.

Example:
    >>> from internal.database.manager import DatabaseManager
    >>> from internal.database.repositories.common import CommonFunctionsRepository
    >>>
    >>> async def example_usage():
    ...     manager = DatabaseManager()
    ...     repo = CommonFunctionsRepository(manager)
    ...     await repo.setSetting("theme", "dark")
    ...     theme = await repo.getSetting("theme", "light")
    ...     all_settings = await repo.getSettings()
    ...     return theme, all_settings

Classes:
    CommonFunctionsRepository: Repository for managing configuration settings
        stored as key-value pairs in the database.
"""

import logging
from typing import Dict, Optional

from .. import utils as dbUtils
from ..manager import DatabaseManager
from .base import BaseRepository

logger = logging.getLogger(__name__)


class CommonFunctionsRepository(BaseRepository):
    """Repository for common database utility functions.

    Provides methods for managing configuration settings stored in the database.
    Settings are stored as key-value pairs and can be used for application-wide
    configuration that needs to persist across restarts.

    This repository extends BaseRepository and implements methods for:
    - Setting individual configuration values
    - Retrieving individual configuration values with optional defaults
    - Retrieving all configuration settings as a dictionary

    Attributes:
        manager: DatabaseManager instance for accessing database providers
            and executing database operations. Inherited from BaseRepository.

    Example:
        >>> repo = CommonFunctionsRepository(database_manager)
        >>> await repo.setSetting("api_key", "secret123")
        >>> key = await repo.getSetting("api_key")
        >>> all_settings = await repo.getSettings()
    """

    __slots__ = ()
    """Restricts instance attributes to prevent dynamic attribute creation."""

    def __init__(self, manager: DatabaseManager) -> None:
        """Initialize the common functions repository.

        Args:
            manager: DatabaseManager instance for accessing database providers
                and executing database operations.

        Raises:
            TypeError: If manager is not a DatabaseManager instance.
        """
        super().__init__(manager)

    ###
    # Global Settings manipulation functions
    ###

    async def setSetting(self, key: str, value: str, *, dataSource: Optional[str] = None) -> bool:
        """Set a configuration setting in the database.

        Stores or updates a key-value pair in the settings table. If the key
        already exists, its value will be replaced. The operation uses
        INSERT OR REPLACE to handle both new and existing keys.

        Args:
            key: Setting key to store. Must be a non-empty string.
            value: Setting value to associate with the key.
            dataSource: Optional data source name for explicit routing. If None,
                uses the default data source. Cannot be a readonly source.

        Returns:
            bool: True if the setting was successfully stored or updated,
                False if an error occurred.

        Raises:
            Exception: If database operation fails (caught and logged, returns False).

        Note:
            Writes to the default data source if dataSource is not specified.
            Cannot write to readonly sources - will raise an exception if attempted.
            The created_at and updated_at timestamps are automatically set to
            the current time.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=False)

            await sqlProvider.execute(
                """
                    INSERT OR REPLACE INTO settings
                    (key, value, created_at, updated_at)
                    VALUES (:key, :value, :createdAt, :updatedAt)
                """,
                {
                    "key": key,
                    "value": value,
                    "createdAt": dbUtils.getCurrentTimestamp(),
                    "updatedAt": dbUtils.getCurrentTimestamp(),
                },
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set setting {key} in {dataSource}: {e}")
            return False

    async def getSetting(
        self, key: str, default: Optional[str] = None, *, dataSource: Optional[str] = None
    ) -> Optional[str]:
        """Get a configuration setting from the database.

        Retrieves the value associated with the specified key from the settings
        table. If the key does not exist, returns the provided default value.

        Args:
            key: Setting key to retrieve. Must be a non-empty string.
            default: Default value to return if the key is not found in the
                database. If None, returns None when key is not found.
            dataSource: Optional data source name for explicit routing. If None,
                uses the default data source.

        Returns:
            Optional[str]: The setting value if found, otherwise the default value.
                Returns None if key is not found and no default is provided.

        Raises:
            Exception: If database operation fails (caught and logged, returns default).

        Note:
            Reads from the default data source if dataSource is not specified.
            The operation is performed on a readonly connection.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)

            row = await sqlProvider.executeFetchOne("SELECT value FROM settings WHERE key = :key", {"key": key})
            return row["value"] if row else default
        except Exception as e:
            logger.error(f"Failed to get setting {key} in {dataSource}: {e}")
            return default

    async def getSettings(self, *, dataSource: Optional[str] = None) -> Dict[str, str]:
        """Get all configuration settings from the database.

        Retrieves all key-value pairs stored in the settings table and returns
        them as a dictionary. This is useful for bulk loading configuration
        or for debugging purposes.

        Args:
            dataSource: Optional data source name for explicit routing. If None,
                uses the default data source.

        Returns:
            Dict[str, str]: Dictionary containing all settings as key-value pairs.
                Returns an empty dictionary if no settings exist or if an error occurs.

        Raises:
            Exception: If database operation fails (caught and logged, returns empty dict).

        Note:
            Reads from the default data source if dataSource is not specified.
            The operation is performed on a readonly connection.
            The returned dictionary includes all columns from the settings table,
            but only the key-value pairs are included in the result.
        """
        try:
            sqlProvider = await self.manager.getProvider(dataSource=dataSource, readonly=True)
            ret = await sqlProvider.executeFetchAll("SELECT * FROM settings")
            return {row["key"]: row["value"] for row in ret}
        except Exception as e:
            logger.error(f"Failed to get settings in {dataSource}: {e}")
            return {}
