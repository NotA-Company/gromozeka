"""
Null storage backend implementation

This module provides a no-op storage backend for testing purposes.
All operations return expected values without performing any actual storage.
"""

from ..utils import sanitizeKey
from .abstract import AbstractStorageBackend


class NullStorageBackend(AbstractStorageBackend):
    """
    No-op storage backend for testing purposes.

    This backend validates keys but performs no actual storage operations.
    All methods return expected values without side effects:
    - store() does nothing and returns immediately
    - get() always returns None
    - exists() always returns False
    - delete() always returns False
    - list() always returns an empty list

    Use cases:
    - Unit testing without actual storage
    - Disabling storage functionality
    - Performance testing without I/O overhead

    Example:
        >>> backend = NullStorageBackend()
        >>> backend.store("test-key", b"data")  # Does nothing
        >>> backend.get("test-key")  # Returns None
        None
        >>> backend.exists("test-key")  # Returns False
        False
    """

    def store(self, key: str, data: bytes) -> None:
        """
        No-op store operation that validates the key but performs no storage.

        Args:
            key: The storage key to validate (will be sanitized)
            data: The binary data (ignored)

        Raises:
            StorageKeyError: If the key is invalid
        """
        # Validate key by sanitizing it (will raise StorageKeyError if invalid)
        sanitizeKey(key)
        # No-op: do nothing with the data

    def get(self, key: str) -> bytes | None:
        """
        No-op get operation that always returns None.

        Args:
            key: The storage key to validate (will be sanitized)

        Returns:
            Always returns None to simulate missing object

        Raises:
            StorageKeyError: If the key is invalid
        """
        # Validate key by sanitizing it (will raise StorageKeyError if invalid)
        sanitizeKey(key)
        return None

    def exists(self, key: str) -> bool:
        """
        No-op exists check that always returns False.

        Args:
            key: The storage key to validate (will be sanitized)

        Returns:
            Always returns False to simulate non-existent object

        Raises:
            StorageKeyError: If the key is invalid
        """
        # Validate key by sanitizing it (will raise StorageKeyError if invalid)
        sanitizeKey(key)
        return False

    def delete(self, key: str) -> bool:
        """
        No-op delete operation that always returns False.

        Args:
            key: The storage key to validate (will be sanitized)

        Returns:
            Always returns False to simulate object not found

        Raises:
            StorageKeyError: If the key is invalid
        """
        # Validate key by sanitizing it (will raise StorageKeyError if invalid)
        sanitizeKey(key)
        return False

    def list(self, prefix: str = "", limit: int | None = None) -> list[str]:
        """
        No-op list operation that always returns an empty list.

        Args:
            prefix: Optional prefix to filter keys (ignored)
            limit: Optional maximum number of keys to return (ignored)

        Returns:
            Always returns an empty list
        """
        # No validation needed for prefix in null backend
        return []
