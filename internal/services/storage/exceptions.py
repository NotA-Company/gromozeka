"""
Storage service exceptions

This module defines the exception hierarchy for the storage service.
All storage-related errors inherit from StorageError base class.
"""


class StorageError(Exception):
    """
    Base exception for all storage service errors.

    This is the parent class for all storage-related exceptions.
    Catch this to handle any storage service error generically.
    """

    pass


class StorageKeyError(StorageError):
    """
    Exception raised when a storage key is invalid.

    This exception is raised when a key fails validation, such as:
    - Contains invalid characters
    - Exceeds maximum length
    - Contains path traversal sequences
    - Is empty or only whitespace

    Args:
        message: Description of why the key is invalid
    """

    pass


class StorageConfigError(StorageError):
    """
    Exception raised when storage configuration is invalid.

    This exception is raised during service initialization when:
    - Required configuration parameters are missing
    - Configuration values are invalid
    - Backend type is not recognized
    - Backend-specific configuration is malformed

    Args:
        message: Description of the configuration error
    """

    pass


class StorageBackendError(StorageError):
    """
    Exception raised when a storage backend operation fails.

    This exception wraps backend-specific errors such as:
    - File system I/O errors
    - Network errors for remote storage
    - Permission errors
    - Storage quota exceeded
    - Backend service unavailable

    Args:
        message: Description of the backend error
        originalError: The original exception that caused this error (optional)
    """

    def __init__(self, message: str, originalError: Exception | None = None):
        """
        Initialize StorageBackendError with message and optional original error.

        Args:
            message: Description of the backend error
            originalError: The original exception that caused this error
        """
        super().__init__(message)
        self.originalError = originalError
