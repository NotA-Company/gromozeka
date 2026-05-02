"""Database manager for Gromozeka bot with configuration and wrapper initialization."""

import logging
from collections.abc import Awaitable, Callable
from typing import Dict, List, Optional, TypedDict

from .providers import BaseSQLProvider, SQLProviderConfig, getSqlProvider

logger = logging.getLogger(__name__)

SQLProviderInitializationHook = Callable[[BaseSQLProvider, str, bool], Awaitable[None]]
"""Async hook function called after SQL provider initialization.

Args:
    provider: The initialized SQL provider instance
    providerName: Name of the provider being initialized
    isReadOnly: Whether the provider is in read-only mode

Returns:
    None
"""


class DatabaseManagerConfig(TypedDict):
    """Configuration for DatabaseManager.

    Defines the structure for database manager configuration including
    default provider, chat-to-provider mappings, and provider configurations.
    """

    default: str
    """Name of the default data source provider."""
    chatMapping: Dict[int, str]
    """Mapping of chat IDs to data source provider names."""
    providers: Dict[str, SQLProviderConfig]
    """Dictionary of provider configurations keyed by provider name."""


class DatabaseManager:
    """Manages database initialization and configuration.

    Handles multiple SQL providers, chat-to-provider routing, and provider
    lifecycle management including initialization and cleanup.
    """

    __slots__ = ("config", "_providers", "_initializationHooks")

    config: DatabaseManagerConfig
    """Database configuration containing providers, default source, and chat mappings."""

    _providers: Dict[str, BaseSQLProvider]
    """Cache of initialized SQL provider instances keyed by provider name."""

    _initializationHooks: List[SQLProviderInitializationHook]
    """List of hooks to call after provider initialization."""

    def __init__(self, config: DatabaseManagerConfig):
        """Initialize DatabaseManager with configuration.

        Args:
            config: Database configuration dict containing providers, default source,
                   and chat mappings

        Raises:
            ValueError: If no providers, no default source, or default source not found
        """

        self.config = config.copy()
        if "providers" not in self.config:
            raise ValueError("No providers found in configuration, dood")
        if "default" not in self.config:
            raise ValueError("No default source found in configuration, dood")
        if self.config["default"] not in self.config["providers"]:
            raise ValueError(
                f"Default source '{self.config['default']}' not found in configuration, "
                "please check your configuration and try again, dood!"
            )
        if "chatMapping" not in self.config:
            # Do not raise error if no chat mappings provided.
            # Just thewat it as empty dict
            self.config["chatMapping"] = {}

        self._providers: Dict[str, BaseSQLProvider] = {}
        self._initializationHooks: List[SQLProviderInitializationHook] = []
        logger.info(f"Database initialized: {self.config}")

    def addProviderInitializationHook(self, hook: SQLProviderInitializationHook) -> None:
        """Add a hook to be called after provider initialization.

        Args:
            hook: Async function to call after provider initialization, receiving
                  the provider, its name, and readonly status

        Returns:
            None
        """
        self._initializationHooks.append(hook)

    async def getProvider(
        self,
        *,
        chatId: Optional[int] = None,
        dataSource: Optional[str] = None,
        readonly: bool = False,
    ) -> BaseSQLProvider:
        """Get the SQL provider instance based on routing parameters.

        Provider selection priority: dataSource > chatId mapping > default source.
        Initializes provider on first access and validates readonly constraints.

        Args:
            chatId: Optional chat ID for provider mapping lookup
            dataSource: Optional explicit data source name to use
            readonly: Whether the operation is read-only (default: False)

        Returns:
            BaseSQLProvider: The SQL provider instance for database operations

        Raises:
            ValueError: If write operation attempted on readonly provider
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

    async def closeAll(self) -> None:
        """Close all database connections and cleanup resources.

        Disconnects all initialized providers and clears the provider cache.
        Should be called during application shutdown to ensure proper resource cleanup.

        Returns:
            None
        """
        logger.info("Closing all database connections...")
        for providerName, provider in self._providers.items():
            try:
                await provider.disconnect()
                logger.debug(f"Disconnected provider '{providerName}'")
            except Exception as e:
                logger.error(f"Error disconnecting provider '{providerName}': {e}")
        self._providers.clear()
        logger.info("All database connections closed")
