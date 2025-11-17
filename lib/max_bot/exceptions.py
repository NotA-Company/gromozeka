"""
Max Bot API Exceptions

This module contains custom exception classes for handling Max Messenger Bot API errors.
"""

import logging
from typing import Any, Dict, Optional

from .constants import (
    ERROR_CODE_INVALID_REQUEST,
    ERROR_CODE_INVALID_TOKEN,
    ERROR_CODE_METHOD_NOT_ALLOWED,
    ERROR_CODE_RATE_LIMIT_EXCEEDED,
    ERROR_CODE_RESOURCE_NOT_FOUND,
    ERROR_CODE_SERVICE_UNAVAILABLE,
)

logger = logging.getLogger(__name__)


class MaxBotError(Exception):
    """Base exception class for all Max Bot API errors, dood!

    All other exceptions in this module inherit from this base class.
    Provides common functionality for error handling and logging.

    Attributes:
        message: Human-readable error message
        code: API error code (if available)
        response: Raw API response data (if available)
    """

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.response = response
        logger.debug(f"MaxBotError: {message} (code: {code})")

    def __str__(self) -> str:
        if self.code:
            return f"{self.message} (code: {self.code})"
        return self.message


class AuthenticationError(MaxBotError):
    """Raised when authentication fails due to invalid or missing token.

    This typically occurs when:
    - The access token is invalid or expired
    - No access token is provided
    - The token doesn't have sufficient permissions
    """

    def __init__(
        self,
        message: str = "Authentication failed. Check your access token.",
        code: Optional[str] = ERROR_CODE_INVALID_TOKEN,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, code, response)


class APIError(MaxBotError):
    """Raised when the API returns an error response.

    This is a general-purpose exception for API errors that don't
    fit into more specific categories like authentication or rate limiting.
    """

    def __init__(
        self, message: str, code: Optional[str] = ERROR_CODE_INVALID_REQUEST, response: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message, code, response)


class RateLimitError(MaxBotError):
    """Raised when the API rate limit is exceeded.

    This occurs when too many requests are sent in a short time period.
    The client should implement exponential backoff and retry logic.
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please try again later.",
        code: Optional[str] = ERROR_CODE_RATE_LIMIT_EXCEEDED,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, code, response)


class ValidationError(MaxBotError):
    """Raised when request validation fails.

    This occurs when the request data doesn't match the API schema,
    such as invalid parameters, missing required fields, or data type mismatches.
    """

    def __init__(
        self,
        message: str,
        code: Optional[str] = ERROR_CODE_INVALID_REQUEST,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, code, response)


class NotFoundError(MaxBotError):
    """Raised when a requested resource is not found.

    This occurs when trying to access a chat, message, or other resource
    that doesn't exist or the bot doesn't have access to.
    """

    def __init__(
        self,
        message: str = "Resource not found.",
        code: Optional[str] = ERROR_CODE_RESOURCE_NOT_FOUND,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, code, response)


class MethodNotAllowedError(MaxBotError):
    """Raised when an HTTP method is not allowed for the endpoint.

    This occurs when trying to use GET on an endpoint that only accepts POST,
    or similar method/endpoint mismatches.
    """

    def __init__(
        self,
        message: str = "Method not allowed for this endpoint.",
        code: Optional[str] = ERROR_CODE_METHOD_NOT_ALLOWED,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, code, response)


class ServiceUnavailableError(MaxBotError):
    """Raised when the API service is temporarily unavailable.

    This occurs when the API is down for maintenance or experiencing
    temporary issues. The client should retry with exponential backoff.
    """

    def __init__(
        self,
        message: str = "Service temporarily unavailable. Please try again later.",
        code: Optional[str] = ERROR_CODE_SERVICE_UNAVAILABLE,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, code, response)


class NetworkError(MaxBotError):
    """Raised when network-related errors occur.

    This includes connection timeouts, DNS resolution failures,
    and other network-level issues that prevent communication with the API.
    """

    def __init__(
        self,
        message: str = "Network error occurred.",
        code: Optional[str] = None,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, code, response)


class ConfigurationError(MaxBotError):
    """Raised when there's a configuration error.

    This occurs when the client is misconfigured, such as missing
    required parameters or invalid configuration values.
    """

    def __init__(self, message: str, code: Optional[str] = None, response: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code, response)


def parseApiError(statusCode: int, responseData: Dict[str, Any]) -> MaxBotError:
    """Parse API error response and return appropriate exception.

    Args:
        statusCode: HTTP status code
        responseData: Parsed JSON response from API

    Returns:
        Appropriate exception instance based on error code and status

    Example:
        >>> try:
        ...     # API call here
        ... except httpx.HTTPStatusError as e:
        ...     error_data = e.response.json()
        ...     raise parseApiError(e.response.status_code, error_data)
    """
    error_code = responseData.get("code")
    error_message = responseData.get("message", "Unknown API error")

    # Map error codes to exception types
    if error_code == ERROR_CODE_INVALID_TOKEN:
        return AuthenticationError(error_message, error_code, responseData)
    elif error_code == ERROR_CODE_RATE_LIMIT_EXCEEDED:
        return RateLimitError(error_message, error_code, responseData)
    elif error_code == ERROR_CODE_RESOURCE_NOT_FOUND:
        return NotFoundError(error_message, error_code, responseData)
    elif error_code == ERROR_CODE_METHOD_NOT_ALLOWED:
        return MethodNotAllowedError(error_message, error_code, responseData)
    elif error_code == ERROR_CODE_SERVICE_UNAVAILABLE:
        return ServiceUnavailableError(error_message, error_code, responseData)
    elif error_code == ERROR_CODE_INVALID_REQUEST:
        return ValidationError(error_message, error_code, responseData)

    # Fallback to status code mapping
    if statusCode == 401:
        return AuthenticationError(error_message, error_code, responseData)
    elif statusCode == 429:
        return RateLimitError(error_message, error_code, responseData)
    elif statusCode == 404:
        return NotFoundError(error_message, error_code, responseData)
    elif statusCode == 405:
        return MethodNotAllowedError(error_message, error_code, responseData)
    elif statusCode == 503:
        return ServiceUnavailableError(error_message, error_code, responseData)
    elif 400 <= statusCode < 500:
        return ValidationError(error_message, error_code, responseData)
    elif 500 <= statusCode < 600:
        return ServiceUnavailableError(error_message, error_code, responseData)

    # Default to generic API error
    return APIError(error_message, error_code, responseData)
