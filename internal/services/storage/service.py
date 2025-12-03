"""
Storage service: Singleton service for object storage operations

This module provides a singleton service that manages object storage operations
through pluggable backend implementations (filesystem, S3, null).
"""

import logging
import threading
from typing import TYPE_CHECKING, Union

from .backends.abstract import AbstractStorageBackend
from .backends.filesystem import FSStorageBackend
from .backends.null import NullStorageBackend
from .backends.s3 import S3StorageBackend
from .exceptions import StorageConfigError

if TYPE_CHECKING:
    from internal.config.manager import ConfigManager

logger = logging.getLogger(__name__)


class StorageService:
    """
    Singleton service for object storage operations.

    This service provides a unified interface for storing and retrieving binary objects
    using different backend implementations. The backend is configured at initialization
    time through the injectConfig method.

    Supported backends:
    - null: No-op backend for testing
    - fs: Filesystem-based storage
    - s3: AWS S3 or S3-compatible storage

    Usage:
        storage = StorageService.getInstance()
        storage.injectConfig(configManager)

        # Store and retrieve objects
        storage.store("my-key", b"data")
        data = storage.get("my-key")
        exists = storage.exists("my-key")
        storage.delete("my-key")

        # List objects
        keys = storage.list(prefix="prefix-", limit=10)

    Thread Safety:
        The singleton instance creation is thread-safe using RLock.
        Individual backend operations depend on backend implementation.
    """

    _instance: Union["StorageService", None] = None
    _lock = threading.RLock()

    def __new__(cls) -> "StorageService":
        """
        Create or return singleton instance with thread safety.

        Returns:
            The singleton StorageService instance
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self):
        """
        Initialize storage service.

        Only runs once due to singleton pattern. Sets up:
        - Backend placeholder (None until injectConfig is called)
        - Initialization flag
        """
        if not hasattr(self, "initialized"):
            self.backend: AbstractStorageBackend | None = None
            self.initialized = False
            logger.info("StorageService created, awaiting configuration, dood!")

    @classmethod
    def getInstance(cls) -> "StorageService":
        """
        Get singleton instance.

        Returns:
            The singleton StorageService instance
        """
        return cls()

    def injectConfig(self, configManager: "ConfigManager") -> None:
        """
        Initialize service with configuration from ConfigManager.

        Reads storage configuration and creates the appropriate backend based on
        the configured type. This method should be called once during application
        initialization.

        Args:
            configManager: The configuration manager containing storage settings

        Raises:
            StorageConfigError: If configuration is invalid or backend creation fails

        Configuration format:
            {
                "type": "fs",  # or "null" or "s3"
                "fs": {"base-dir": "./storage/objects"},
                "s3": {
                    "endpoint": "https://s3.amazonaws.com",
                    "region": "us-east-1",
                    "key-id": "...",
                    "key-secret": "...",
                    "bucket": "my-bucket",
                    "prefix": ""
                }
            }
        """
        try:
            # Get storage configuration from ConfigManager
            config = configManager.getStorageConfig()  # pyright: ignore[reportAttributeAccessIssue]

            if not config:
                raise StorageConfigError("Storage configuration is missing")

            storageType = config.get("type")
            if not storageType:
                raise StorageConfigError("Storage type is not specified in configuration")

            # Create appropriate backend based on type
            if storageType == "null":
                self.backend = NullStorageBackend()
                logger.info("Initialized NullStorageBackend, dood!")

            elif storageType == "fs":
                fsConfig = config.get("fs")
                if not fsConfig:
                    raise StorageConfigError("Filesystem storage configuration is missing")

                baseDir = fsConfig.get("base-dir")
                if not baseDir:
                    raise StorageConfigError("Filesystem base-dir is not specified")

                self.backend = FSStorageBackend(baseDir)
                logger.info(f"Initialized FSStorageBackend with base-dir: {baseDir}, dood!")

            elif storageType == "s3":
                s3Config = config.get("s3")
                if not s3Config:
                    raise StorageConfigError("S3 storage configuration is missing")

                # Validate required S3 parameters
                requiredParams = ["endpoint", "region", "key-id", "key-secret", "bucket"]
                missingParams = [p for p in requiredParams if not s3Config.get(p)]
                if missingParams:
                    raise StorageConfigError(
                        f"S3 configuration missing required parameters: {', '.join(missingParams)}"
                    )

                self.backend = S3StorageBackend(
                    endpoint=s3Config["endpoint"],
                    region=s3Config["region"],
                    keyId=s3Config["key-id"],
                    keySecret=s3Config["key-secret"],
                    bucket=s3Config["bucket"],
                    prefix=s3Config.get("prefix", ""),
                )
                logger.info(
                    f"Initialized S3StorageBackend with bucket: {self.backend.bucket}, "
                    f"prefix: {self.backend.prefix}, dood!"
                )

            else:
                raise StorageConfigError(f"Unknown storage type: {storageType}")

            self.initialized = True
            logger.info(f"StorageService initialized with {storageType} backend, dood!")

        except StorageConfigError:
            raise
        except Exception as e:
            raise StorageConfigError(f"Failed to initialize storage service: {e}") from e

    def _ensureInitialized(self) -> None:
        """
        Ensure the service is initialized before operations.

        Raises:
            StorageConfigError: If service is not initialized
        """
        if not self.initialized or self.backend is None:
            raise StorageConfigError("StorageService is not initialized. Call injectConfig() first, dood!")

    def store(self, key: str, data: bytes) -> None:
        """
        Store binary data under the specified key.

        Args:
            key: The storage key (unique identifier)
            data: The binary data to store

        Raises:
            StorageConfigError: If service is not initialized
            StorageKeyError: If the key is invalid
            StorageBackendError: If the storage operation fails
        """
        self._ensureInitialized()
        assert self.backend is not None  # For type checker
        self.backend.store(key, data)
        logger.debug(f"Stored object with key: {key}, dood!")

    def get(self, key: str) -> bytes | None:
        """
        Retrieve binary data for the specified key.

        Args:
            key: The storage key to retrieve

        Returns:
            The binary data if the key exists, None if not found

        Raises:
            StorageConfigError: If service is not initialized
            StorageKeyError: If the key is invalid
            StorageBackendError: If the retrieval operation fails
        """
        self._ensureInitialized()
        assert self.backend is not None  # For type checker
        data = self.backend.get(key)
        if data is not None:
            logger.debug(f"Retrieved object with key: {key}, dood!")
        else:
            logger.warning(f"Object not found with key: {key}, dood!")
        return data

    def exists(self, key: str) -> bool:
        """
        Check if an object exists for the specified key.

        Args:
            key: The storage key to check

        Returns:
            True if the key exists, False otherwise

        Raises:
            StorageConfigError: If service is not initialized
            StorageKeyError: If the key is invalid
            StorageBackendError: If the existence check fails
        """
        self._ensureInitialized()
        assert self.backend is not None  # For type checker
        exists = self.backend.exists(key)
        logger.debug(f"Existence check for key {key}: {exists}, dood!")
        return exists

    def delete(self, key: str) -> bool:
        """
        Delete the object for the specified key.

        Args:
            key: The storage key to delete

        Returns:
            True if the object was deleted, False if it didn't exist

        Raises:
            StorageConfigError: If service is not initialized
            StorageKeyError: If the key is invalid
            StorageBackendError: If the deletion operation fails
        """
        self._ensureInitialized()
        assert self.backend is not None  # For type checker
        deleted = self.backend.delete(key)
        if deleted:
            logger.debug(f"Deleted object with key: {key}, dood!")
        else:
            logger.warning(f"Object not found for deletion with key: {key}, dood!")
        return deleted

    def list(self, prefix: str = "", limit: int | None = None) -> list[str]:
        """
        List all keys with an optional prefix filter and limit.

        Args:
            prefix: Optional prefix to filter keys (default: "" for all keys)
            limit: Optional maximum number of keys to return (default: None for no limit)

        Returns:
            List of keys matching the prefix, up to the specified limit.
            Returns empty list if no keys match.

        Raises:
            StorageConfigError: If service is not initialized
            StorageBackendError: If the list operation fails
        """
        self._ensureInitialized()
        assert self.backend is not None  # For type checker
        keys = self.backend.list(prefix=prefix, limit=limit)
        logger.debug(f"Listed {len(keys)} objects with prefix: '{prefix}', dood!")
        return keys
