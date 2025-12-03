"""
Filesystem storage backend implementation

This module provides a storage backend that stores objects as files
in a local directory with atomic operations and proper error handling.
"""

import os
from pathlib import Path

from ..exceptions import StorageBackendError, StorageKeyError
from ..utils import sanitizeKey
from .abstract import AbstractStorageBackend


class FSStorageBackend(AbstractStorageBackend):
    """
    Filesystem-based storage backend.

    Stores objects as files in a local directory using sanitized filenames.
    Uses a flat storage structure without subdirectories for simplicity.

    Features:
    - Automatic directory creation if baseDir doesn't exist
    - Atomic file operations where possible
    - File permissions set to 0o644 (readable by all, writable by owner)
    - Proper error handling with StorageBackendError wrapping

    Args:
        baseDir: Base directory path for storage (will be created if needed)

    Raises:
        StorageBackendError: If baseDir cannot be created or accessed

    Example:
        >>> backend = FSStorageBackend("/tmp/storage")
        >>> backend.store("test-key", b"data")
        >>> backend.get("test-key")
        b'data'
        >>> backend.exists("test-key")
        True
    """

    def __init__(self, baseDir: str):
        """
        Initialize filesystem storage backend.

        Args:
            baseDir: Base directory path for storage

        Raises:
            StorageBackendError: If baseDir cannot be created or is not a directory
        """
        self.baseDir = Path(baseDir)

        # Create base directory if it doesn't exist
        try:
            self.baseDir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise StorageBackendError(f"Failed to create base directory '{baseDir}': {e}", originalError=e)

        # Verify it's actually a directory
        if not self.baseDir.is_dir():
            raise StorageBackendError(f"Base path '{baseDir}' exists but is not a directory")

    def _getFilePath(self, key: str) -> Path:
        """
        Get the full file path for a sanitized key.

        Args:
            key: The storage key (will be sanitized)

        Returns:
            Path object for the file

        Raises:
            StorageKeyError: If the key is invalid
        """
        sanitizedKey = sanitizeKey(key)
        return self.baseDir / sanitizedKey

    def store(self, key: str, data: bytes) -> None:
        """
        Store binary data to a file.

        Uses atomic write operation by writing to a temporary file first,
        then renaming it to the target filename.

        Args:
            key: The storage key (will be sanitized)
            data: The binary data to store

        Raises:
            StorageKeyError: If the key is invalid
            StorageBackendError: If the write operation fails
        """
        filePath = self._getFilePath(key)
        tempPath = filePath.with_suffix(filePath.suffix + ".tmp")

        try:
            # Write to temporary file first
            with open(tempPath, "wb") as f:
                f.write(data)

            # Set file permissions to 0o644
            os.chmod(tempPath, 0o644)

            # Atomic rename to target file
            tempPath.replace(filePath)

        except Exception as e:
            # Clean up temporary file if it exists
            if tempPath.exists():
                try:
                    tempPath.unlink()
                except Exception:
                    pass  # Ignore cleanup errors

            raise StorageBackendError(f"Failed to store object with key '{key}': {e}", originalError=e)

    def get(self, key: str) -> bytes | None:
        """
        Retrieve binary data from a file.

        Args:
            key: The storage key (will be sanitized)

        Returns:
            The binary data if the file exists, None if not found

        Raises:
            StorageKeyError: If the key is invalid
            StorageBackendError: If the read operation fails (not for missing files)
        """
        filePath = self._getFilePath(key)

        # Return None if file doesn't exist
        if not filePath.exists():
            return None

        try:
            with open(filePath, "rb") as f:
                return f.read()
        except FileNotFoundError:
            # File was deleted between exists check and read
            return None
        except Exception as e:
            raise StorageBackendError(f"Failed to read object with key '{key}': {e}", originalError=e)

    def exists(self, key: str) -> bool:
        """
        Check if a file exists for the specified key.

        Args:
            key: The storage key (will be sanitized)

        Returns:
            True if the file exists, False otherwise

        Raises:
            StorageKeyError: If the key is invalid
            StorageBackendError: If the existence check fails
        """
        try:
            filePath = self._getFilePath(key)
            return filePath.exists() and filePath.is_file()
        except (StorageKeyError, StorageBackendError):
            raise
        except Exception as e:
            raise StorageBackendError(f"Failed to check existence of key '{key}': {e}", originalError=e)

    def delete(self, key: str) -> bool:
        """
        Delete the file for the specified key.

        Args:
            key: The storage key (will be sanitized)

        Returns:
            True if the file was deleted, False if it didn't exist

        Raises:
            StorageKeyError: If the key is invalid
            StorageBackendError: If the deletion fails
        """
        filePath = self._getFilePath(key)

        # Return False if file doesn't exist
        if not filePath.exists():
            return False

        try:
            filePath.unlink()
            return True
        except FileNotFoundError:
            # File was deleted between exists check and unlink
            return False
        except Exception as e:
            raise StorageBackendError(f"Failed to delete object with key '{key}': {e}", originalError=e)

    def list(self, prefix: str = "", limit: int | None = None) -> list[str]:
        """
        List all files in the base directory matching the prefix.

        Args:
            prefix: Optional prefix to filter filenames (default: "" for all files)
            limit: Optional maximum number of keys to return (default: None for no limit)

        Returns:
            List of filenames matching the prefix, up to the specified limit.
            Returns empty list if no files match.

        Raises:
            StorageBackendError: If the list operation fails
        """
        try:
            # Get all files in base directory (not subdirectories)
            allFiles = [f.name for f in self.baseDir.iterdir() if f.is_file()]

            # Filter by prefix if provided
            if prefix:
                matchingFiles = [f for f in allFiles if f.startswith(prefix)]
            else:
                matchingFiles = allFiles

            # Sort for consistent ordering
            matchingFiles.sort()

            # Apply limit if specified
            if limit is not None and limit > 0:
                return matchingFiles[:limit]

            return matchingFiles

        except Exception as e:
            raise StorageBackendError(f"Failed to list objects with prefix '{prefix}': {e}", originalError=e)
