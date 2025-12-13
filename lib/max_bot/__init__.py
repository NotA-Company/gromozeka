"""
Max Bot Client Library

A comprehensive async Python client for the Max Messenger Bot API.

This library provides a clean, type-safe interface for interacting with
the Max Messenger Bot API using httpx with proper authentication,
error handling, and retry logic.

Basic usage:
    >>> from lib.max_bot import MaxBotClient
    >>>
    >>> async with MaxBotClient("your_access_token") as client:
    ...     bot_info = await client.getMyInfo()
    ...     print(f"Bot name: {bot_info['name']}")

For more advanced usage and examples, see the README.md file.
"""

from .client import MaxBotClient
from .constants import (
    MAX_FILE_SIZE,
    MAX_MESSAGE_LENGTH,
    MAX_RETRIES,
    AttachmentType,
    ButtonType,
    TextFormat,
)
from .exceptions import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    MaxBotError,
    MethodNotAllowedError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
    AttachmentNotReadyError,
)
from .utils import MessageLinkToMessage

# Public API
__all__ = [
    # Main client
    "MaxBotClient",
    # Constants
    "MAX_RETRIES",
    "MAX_MESSAGE_LENGTH",
    "MAX_FILE_SIZE",
    # Enums
    "TextFormat",
    "ButtonType",
    "AttachmentType",
    # Exceptions
    "MaxBotError",
    "AuthenticationError",
    "APIError",
    "RateLimitError",
    "ValidationError",
    "NotFoundError",
    "MethodNotAllowedError",
    "ServiceUnavailableError",
    "NetworkError",
    "ConfigurationError",
    "AttachmentNotReadyError",
    # Utils
    "MessageLinkToMessage",
]
