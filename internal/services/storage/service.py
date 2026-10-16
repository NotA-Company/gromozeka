"""
Storage service: Scoped singleton service for object storage operations

This module provides per-scope singleton services that manage object storage
operations through pluggable backend implementations (filesystem, S3, null).
Each sanctioned scope (see StorageScope) resolves to its own StorageService
instance, configured from its own config table.
"""

import logging
import threading
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Dict

from .backends.abstract import AbstractStorageBackend
from .backends.filesystem import FSStorageBackend
from .backends.null import NullStorageBackend
from .backends.s3 import S3StorageBackend
from .exceptions import StorageConfigError

if TYPE_CHECKING:
    from internal.config.manager import ConfigManager

logger = logging.getLogger(__name__)


class StorageScope(StrEnum):
    """
    Sanctioned storage scopes.

    Each member names a ``[storage.storages.{value}]`` config table; the
    DEFAULT scope is the exception — it reads the top-level ``[storage]``
    table (its long-standing home, kept for backward compatibility). This is
    the closed set of sanctioned scopes at design time: adding a new storage
    later means adding one enum member plus its config table.

    Attributes:
        DEFAULT: The default store (top-level ``[storage]`` table; the
            long-standing attachments store). Argless ``getInstance()`` /
            ``injectConfig(configManager)`` calls resolve here.
        VISION: The native-vision store (``[storage.storages.vision]``
            table). An absent table resolves to a null backend (feature
            off); a present-but-malformed table crashes at inject time,
            with parity to the default table.
    """

    DEFAULT = "default"
    VISION = "vision"


def _buildBackend(
    config: Dict[str, Any],
    # Inherited-``Any`` exception (Phase 1 review precedent, same pattern as
    # ``ModelImagesMessage.toDict``'s overrides): the parameter type is forced
    # by ``ConfigManager.getStorageConfig()``'s declared
    # ``Dict[str, Any]`` return contract — this helper is the behavior-
    # preserving extraction of the old inline if/elif chain (scoped-storage
    # design v1 §4.3), and re-typing it to ``Dict[str, object]`` would trip
    # pyright on the un-narrowed ``.get`` calls below without adding safety.
) -> AbstractStorageBackend:
    """
    Build a storage backend from a storage config table.

    Shared validation/backend-construction chain used for the default
    ``[storage]`` table and for every named ``[storage.storages.*]`` table —
    both paths must validate identically (bad named config crashes startup
    exactly like a bad default config).

    Args:
        config: Storage configuration dictionary with the same shape as the
            ``[storage]`` table

    Returns:
        The configured backend instance

    Raises:
        StorageConfigError: If configuration is invalid or backend creation fails
    """
    storageType = config.get("type")
    if not storageType:
        raise StorageConfigError("Storage type is not specified in configuration")

    # Create appropriate backend based on type
    if storageType == "null":
        backend: AbstractStorageBackend = NullStorageBackend()
        logger.info("Initialized NullStorageBackend")

    elif storageType == "fs":
        fsConfig = config.get("fs")
        if not fsConfig:
            raise StorageConfigError("Filesystem storage configuration is missing")

        baseDir = fsConfig.get("base-dir")
        if not baseDir:
            raise StorageConfigError("Filesystem base-dir is not specified")

        backend = FSStorageBackend(baseDir)
        logger.info(f"Initialized FSStorageBackend with base-dir: {baseDir}")

    elif storageType == "s3":
        s3Config = config.get("s3")
        if not s3Config:
            raise StorageConfigError("S3 storage configuration is missing")

        # Validate required S3 parameters
        requiredParams = ["endpoint", "region", "key-id", "key-secret", "bucket"]
        missingParams = [p for p in requiredParams if not s3Config.get(p)]
        if missingParams:
            raise StorageConfigError(f"S3 configuration missing required parameters: {', '.join(missingParams)}")

        backend = S3StorageBackend(
            endpoint=s3Config["endpoint"],
            region=s3Config["region"],
            keyId=s3Config["key-id"],
            keySecret=s3Config["key-secret"],
            bucket=s3Config["bucket"],
            prefix=s3Config.get("prefix", ""),
        )
        logger.info(f"Initialized S3StorageBackend with bucket: {backend.bucket}, " f"prefix: {backend.prefix}")

    else:
        raise StorageConfigError(f"Unknown storage type: {storageType}")

    return backend


class StorageService:
    """
    Scoped singleton service for object storage operations.

    This service provides a unified interface for storing and retrieving binary objects
    using different backend implementations. The backend is configured at initialization
    time through the injectConfig method.

    One instance exists per StorageScope (see the ``_instances`` registry);
    the DEFAULT scope is the instance every arg-less ``getInstance()`` call
    has always received, so existing call sites are unaffected.

    Supported backends:
    - null: No-op backend for testing
    - fs: Filesystem-based storage
    - s3: AWS S3 or S3-compatible storage

    Usage:
        storage = StorageService.getInstance()
        storage.injectConfig(configManager)

        # Scoped access (e.g. the native-vision store)
        vision = StorageService.getInstance(StorageScope.VISION)
        vision.injectConfig(configManager, scope=StorageScope.VISION)

        # Store and retrieve objects
        storage.store("my-key", b"data")
        data = storage.get("my-key")
        exists = storage.exists("my-key")
        storage.delete("my-key")

        # List objects
        keys = storage.list(prefix="prefix-", limit=10)

    Thread Safety:
        Per-scope singleton instance creation and first-time initialization
        are thread-safe using a class-level RLock.
        Individual backend operations depend on backend implementation.
    """

    _instances: Dict[str, "StorageService"] = {}
    _lock = threading.RLock()

    def __new__(cls, scope: StorageScope = StorageScope.DEFAULT) -> "StorageService":
        """
        Create or return the per-scope singleton instance with thread safety.

        Args:
            scope: The storage scope identifying which instance to return.
                Must be a StorageScope member (no string coercion — a raw
                string fails fast on ``scope.value`` by design)

        Returns:
            The StorageService instance registered for the given scope
        """
        with cls._lock:
            if scope.value not in cls._instances:
                cls._instances[scope.value] = super().__new__(cls)
            return cls._instances[scope.value]

    def __init__(self, scope: StorageScope = StorageScope.DEFAULT) -> None:
        """
        Initialize storage service.

        Only runs once per scoped instance due to the scoped singleton pattern.
        The ``hasattr`` guard and the initialization assignments run under the
        class lock so a concurrent first-time caller cannot re-run them (and
        cannot reset ``backend``/``initialized`` on an instance another thread
        has already configured). The ``scope`` parameter (forwarded by Python
        from ``__new__``) is retained as the instance's bound construction
        scope, which ``injectConfig`` validates against.

        Args:
            scope: The storage scope this instance was created for
        """
        with self._lock:
            if not hasattr(self, "initialized"):
                self.scope: StorageScope = scope
                self.backend: AbstractStorageBackend | None = None
                self.initialized = False
                logger.info("StorageService created, awaiting configuration")

    @classmethod
    def getInstance(cls, scope: StorageScope = StorageScope.DEFAULT) -> "StorageService":
        """
        Get the singleton instance for the given scope.

        Args:
            scope: The storage scope (default: StorageScope.DEFAULT — the
                same instance every existing arg-less call site receives)

        Returns:
            The StorageService instance for the given scope
        """
        return cls(scope)

    def injectConfig(self, configManager: "ConfigManager", scope: StorageScope = StorageScope.DEFAULT) -> None:
        """
        Initialize this scope's instance with configuration from ConfigManager.

        For the DEFAULT scope, reads the top-level ``[storage]`` table. For
        any other scope, reads the ``[storage.storages.{scope.value}]`` table:
        an absent table silently resolves to a null backend (feature off),
        while a present table is validated exactly like the default one (bad
        config raises, never falls back).

        This method should be called once per scope during application
        initialization.

        Args:
            configManager: The configuration manager containing storage settings
            scope: The storage scope to configure (default: StorageScope.DEFAULT).
                Must match the scope this instance was created for

        Raises:
            ValueError: If ``scope`` does not match the scope this instance was
                created for (e.g. an arg-less call on the VISION instance).
                Raised before any state changes, so the instance's backend is
                never silently redirected to another scope's storage
            StorageConfigError: If configuration is invalid or backend creation fails

        Configuration format (identical for the default and every named table):
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
        if scope is not self.scope:
            raise ValueError(
                f"injectConfig scope mismatch: instance was created for scope "
                f"'{self.scope.value}' but injectConfig was called with scope "
                f"'{scope.value}'; use StorageService.getInstance(scope) to get "
                f"the instance for the target scope"
            )

        try:
            if scope is StorageScope.DEFAULT:
                # Get the default storage configuration from ConfigManager
                config = configManager.getStorageConfig()  # pyright: ignore[reportAttributeAccessIssue]

                if not config:
                    raise StorageConfigError("Storage configuration is missing")
            else:
                # Named scope: read [storage.storages.{scope.value}] out of the
                # whole [storage] table (deep-merged by the config loader)
                storages = configManager.getStorageConfig().get(
                    "storages", {}
                )  # pyright: ignore[reportAttributeAccessIssue]
                config = storages.get(scope.value) if isinstance(storages, dict) else None

                if config is None:
                    # Absent named storage = feature explicitly off, NOT an error
                    self.backend = NullStorageBackend()
                    self.initialized = True
                    logger.info(f"StorageService scope '{scope.value}' not configured; using NullStorageBackend")
                    return

            self.backend = _buildBackend(config)
            self.initialized = True
            logger.info(f"StorageService scope '{scope.value}' initialized with {config.get('type')} backend")

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
            raise StorageConfigError("StorageService is not initialized. Call injectConfig() first")

    @property
    def backendType(self) -> str | None:
        """Name of the configured backend type, for read-only introspection.

        Mirrors the ``type`` value accepted by :meth:`injectConfig`, so callers
        can adapt behavior without reaching into the backend object (e.g. the
        native-vision feature warns when storage is the no-op null backend).

        Returns:
            ``"null"``, ``"fs"`` or ``"s3"`` per the configured backend class,
            ``None`` when the service is not initialized (no backend yet), or
            the backend class name for unknown custom backends.
        """
        if self.backend is None:
            return None
        if isinstance(self.backend, NullStorageBackend):
            return "null"
        if isinstance(self.backend, FSStorageBackend):
            return "fs"
        if isinstance(self.backend, S3StorageBackend):
            return "s3"
        return type(self.backend).__name__

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
        logger.debug(f"Stored object with key: {key}")

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
            logger.debug(f"Retrieved object with key: {key}")
        else:
            logger.warning(f"Object not found with key: {key}")
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
        logger.debug(f"Existence check for key {key}: {exists}")
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
            logger.debug(f"Deleted object with key: {key}")
        else:
            logger.warning(f"Object not found for deletion with key: {key}")
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
        logger.debug(f"Listed {len(keys)} objects with prefix: '{prefix}'")
        return keys
