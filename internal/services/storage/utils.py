"""
Storage service utility functions

This module provides utility functions for the storage service,
including key sanitization to prevent path traversal attacks.
"""

import re

from .exceptions import StorageKeyError

# Maximum allowed key length
MAX_KEY_LENGTH = 255

# Minimum allowed key length
MIN_KEY_LENGTH = 1

# Regex pattern for allowed characters: alphanumeric, underscore, hyphen, dot
ALLOWED_CHARS_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


def sanitizeKey(key: str) -> str:
    """
    Sanitize a storage key to prevent path traversal and ensure safe filenames.

    This function performs the following sanitization steps in order:
    1. Remove null bytes and control characters (ASCII 0-31 and 127)
    2. Replace path separators (/, \\) with underscores
    3. Remove double-dot sequences (..)
    4. Strip dangerous leading/trailing characters (whitespace, dots, underscores)
    5. Apply regex to allow only safe characters (alphanumeric, underscore, hyphen, dot)
    6. Validate length is between 1-255 characters

    Args:
        key: The storage key to sanitize

    Returns:
        The sanitized key string

    Raises:
        StorageKeyError: If the key is invalid or becomes invalid after sanitization
            - Key is empty or only whitespace
            - Key contains only invalid characters
            - Key length exceeds maximum (255 characters)
            - Key becomes empty after sanitization

    Examples:
        >>> sanitizeKey("valid-key.txt")
        'valid-key.txt'
        >>> sanitizeKey("../../../etc/passwd")
        'etc_passwd'
        >>> sanitizeKey("file/with/slashes")
        'file_with_slashes'
    """
    if not key or not key.strip():
        raise StorageKeyError("Storage key cannot be empty or only whitespace")

    # Step 1: Remove null bytes and control characters (ASCII 0-31 and 127)
    sanitized = "".join(char for char in key if ord(char) > 31 and ord(char) != 127)

    # Step 2: Replace path separators with underscores
    sanitized = sanitized.replace("/", "_").replace("\\", "_")

    # Step 3: Remove double-dot sequences
    sanitized = sanitized.replace("..", "")

    # Step 4: Strip dangerous leading/trailing characters
    # Remove leading/trailing whitespace, dots, and underscores
    sanitized = sanitized.strip(" ._")

    # Step 5: Apply regex to allow only safe characters
    # Remove any characters that don't match the allowed pattern
    sanitized = "".join(char for char in sanitized if ALLOWED_CHARS_PATTERN.match(char))

    # Step 6: Validate length
    if len(sanitized) < MIN_KEY_LENGTH:
        raise StorageKeyError(f"Storage key is empty or too short after sanitization. Original key: '{key}'")

    if len(sanitized) > MAX_KEY_LENGTH:
        raise StorageKeyError(
            f"Storage key exceeds maximum length of {MAX_KEY_LENGTH} characters. " f"Length: {len(sanitized)}"
        )

    return sanitized
