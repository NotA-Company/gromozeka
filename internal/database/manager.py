"""Database manager for Gromozeka bot with configuration and wrapper initialization."""

import logging
from collections.abc import Awaitable, Callable
from typing import Dict, List, Optional, TypedDict

from .providers import BaseSQLProvider, SQLProviderConfig, getSqlProvider

logger = logging.getLogger(__name__)

SQLProviderInitializationHook = Callable[[BaseSQLProvider, str, bool], Awaitable[None]]


class DatabaseManagerConfig(TypedDict):
    """TODO: write docstring"""

    default: str
    """TODO: write docstring"""
    chatMapping: Dict[int, str]
    """TODO: write docstring"""
    providers: Dict[str, SQLProviderConfig]
    """TODO: write docstring"""


class DatabaseManager:
    """Manages database initialization and configuration.

    Initializes DatabaseWrapper with provided configuration and handles database setup.
    """

    __slots__ = ("config", "_providers", "_initializationHooks")

    def __init__(self, config: DatabaseManagerConfig):
        """Initialize DatabaseManager with configuration.

        Args:
            config: Database configuration dict
        """
        self.config = config
        self._providers: Dict[str, BaseSQLProvider] = {}
        self._initializationHooks: List[SQLProviderInitializationHook] = []
        logger.info(f"Database initialized: {self.config}")

    def addProviderInitializationHook(self, hook: SQLProviderInitializationHook) -> None:
        """Add a hook to be called after provider initialization.

        Args:
            hook: Hook to be called
        """
        self._initializationHooks.append(hook)

    async def getProvider(
        self,
        *,
        chatId: Optional[int] = None,
        dataSource: Optional[str] = None,
        readonly: bool = False,
    ) -> BaseSQLProvider:
        """Get the SQL provider instance.

        Returns:
            SQL provider instance for database operations
        """

        providerName: str

        # Explicit dataSource parameter
        if dataSource is not None:
            if dataSource not in self.config["providers"]:
                logger.warning(
                    f"Explicit dataSource '{dataSource}' not found in configuration, "
                    f"falling back to default source '{self.config["default"]}', dood!"
                )
                providerName = self.config["default"]
            else:
                # logger.debug(f"Using explicit dataSource '{dataSource}'")
                providerName = dataSource

        # ChatId mapping lookup
        elif chatId is not None:
            if chatId in self.config["chatMapping"]:
                mappedSource = self.config["chatMapping"][chatId]
                # Validate mapped source still exists
                if mappedSource not in self.config["providers"]:
                    logger.warning(
                        f"Chat {chatId} mapped to non-existent source '{mappedSource}', "
                        f"falling back to default source '{self.config["default"]}', dood!"
                    )
                    providerName = self.config["default"]
                else:
                    # logger.debug(f"Using chatId {chatId} mapping to source '{mappedSource}'")
                    providerName = mappedSource
            else:
                # logger.debug(
                #     f"Chat {chatId} not in mapping, using default source "
                #     f"'{self._defaultSource}'"
                # )
                providerName = self.config["default"]

        # Default source fallback
        else:
            # logger.debug(
            #     "No routing parameters provided, using default source "
            #     f"'{self._defaultSource}'"
            # )
            providerName = self.config["default"]

        if providerName not in self._providers:
            logger.debug(f"Initializing provider '{providerName}'...")
            newProvider = getSqlProvider(self.config["providers"][providerName])
            self._providers[providerName] = newProvider
            providerIsReadOnly = await newProvider.isReadOnly()
            for hook in self._initializationHooks:
                await hook(newProvider, providerName, providerIsReadOnly)

        sourceProvider = self._providers[providerName]
        # Readonly validation - check before returning connection

        if not readonly and await sourceProvider.isReadOnly():
            raise ValueError(
                f"Cannot perform write operation on readonly source '{providerName}', dood! "
                f"This source is configured as readonly."
            )

        return sourceProvider
