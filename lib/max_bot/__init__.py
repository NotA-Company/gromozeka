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
    API_BASE_URL,
    API_VERSION,
    DEFAULT_TIMEOUT,
    HTTP_DELETE,
    HTTP_GET,
    HTTP_PATCH,
    HTTP_POST,
    HTTP_PUT,
    MAX_FILE_SIZE,
    MAX_MESSAGE_LENGTH,
    MAX_RETRIES,
    AttachmentType,
    ButtonType,
    ChatStatus,
    ChatType,
    SenderAction,
    TextFormat,
    UpdateType,
    UploadType,
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
    parseApiError,
)

__version__ = API_VERSION
__author__ = "Max Bot Client Library"
__email__ = "support@max.ru"

# Public API
__all__ = [
    # Main client
    "MaxBotClient",
    # Constants
    "API_BASE_URL",
    "API_VERSION",
    "DEFAULT_TIMEOUT",
    "MAX_RETRIES",
    "MAX_MESSAGE_LENGTH",
    "MAX_FILE_SIZE",
    # HTTP methods
    "HTTP_GET",
    "HTTP_POST",
    "HTTP_PUT",
    "HTTP_DELETE",
    "HTTP_PATCH",
    # Enums
    "ChatType",
    "ChatStatus",
    "UpdateType",
    "SenderAction",
    "UploadType",
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
    "parseApiError",
]

# Set default logging level
import logging

logging.getLogger(__name__).addHandler(logging.NullHandler())
