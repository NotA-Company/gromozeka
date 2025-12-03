"""
Abstract storage backend interface

This module defines the abstract base class that all storage backends must implement.
It provides a consistent interface for storage operations across different backend types.
"""

from abc import ABC, abstractmethod


class AbstractStorageBackend(ABC):
    """
    Abstract base class for storage backends.

    All storage backend implementations must inherit from this class and implement
    all abstract methods. This ensures a consistent interface across different
    storage types (filesystem, S3, null, etc.).

    Implementations should handle backend-specific errors and wrap them in
    StorageBackendError when appropriate.
    """

    @abstractmethod
    def store(self, key: str, data: bytes) -> None:
        """
        Store binary data under the specified key.

        The key should already be sanitized before calling this method.
        If an object with the same key already exists, it will be overwritten.

        Args:
            key: The sanitized storage key (unique identifier)
            data: The binary data to store

        Raises:
            StorageBackendError: If the storage operation fails
        """
        pass

    @abstractmethod
    def get(self, key: str) -> bytes | None:
        """
        Retrieve binary data for the specified key.

        Args:
            key: The sanitized storage key to retrieve

        Returns:
            The binary data if the key exists, None if the key does not exist

        Raises:
            StorageBackendError: If the retrieval operation fails (not for missing keys)
        """
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """
        Check if an object exists for the specified key.

        Args:
            key: The sanitized storage key to check

        Returns:
            True if the key exists, False otherwise

        Raises:
            StorageBackendError: If the existence check fails
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        Delete the object for the specified key.

        Args:
            key: The sanitized storage key to delete

        Returns:
            True if the object was deleted, False if the key did not exist

        Raises:
            StorageBackendError: If the deletion operation fails
        """
        pass

    @abstractmethod
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
            StorageBackendError: If the list operation fails
        """
        pass
