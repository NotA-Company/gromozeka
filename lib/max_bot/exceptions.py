"""Max Bot API Exceptions.

This module provides custom exception classes for handling Max Messenger Bot API errors.
All exceptions inherit from MaxBotError and include support for error codes and raw API responses.

The module includes specific exceptions for common API error scenarios:
- AuthenticationError: Invalid or expired tokens
- APIError: General API errors
- RateLimitError: Rate limit exceeded
- AttachmentNotReadyError: Attachment still processing
- ValidationError: Request validation failures
- NotFoundError: Resource not found
- MethodNotAllowedError: Invalid HTTP method
- ServiceUnavailableError: Service temporarily unavailable
- NetworkError: Network-related issues
- ConfigurationError: Client configuration errors

The parseApiError function provides automatic error parsing from API responses.
"""

import logging
from typing import Any, Dict, Optional

from .constants import (
    ERROR_CODE_ATTACHMENT_NOT_READY,
    ERROR_CODE_INVALID_REQUEST,
    ERROR_CODE_INVALID_TOKEN,
    ERROR_CODE_METHOD_NOT_ALLOWED,
    ERROR_CODE_RATE_LIMIT_EXCEEDED,
    ERROR_CODE_RESOURCE_NOT_FOUND,
    ERROR_CODE_SERVICE_UNAVAILABLE,
)

logger = logging.getLogger(__name__)


class MaxBotError(Exception):
    """Base exception class for all Max Bot API errors.

    All other exceptions in this module inherit from this base class.
    Provides common functionality for error handling and logging.

    Args:
        message: Human-readable error message describing the error.
        code: API error code from the Max Bot API, if available.
        response: Raw API response data as a dictionary, if available.

    Attributes:
        message: Human-readable error message describing the error.
        code: API error code from the Max Bot API, if available.
        response: Raw API response data as a dictionary, if available.
    """

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize MaxBotError with message, code, and response.

        Args:
            message: Human-readable error message describing the error.
            code: API error code from the Max Bot API, if available.
            response: Raw API response data as a dictionary, if available.
        """
        super().__init__(message)
        self.message = message
        self.code = code
        self.response = response
        logger.debug(f"MaxBotError: {message} (code: {code})")

    def __str__(self) -> str:
        """Return string representation of the error.

        Returns:
            Error message with error code if available, otherwise just the message.
        """
        if self.code:
            return f"{self.message} (code: {self.code})"
        return self.message


class AuthenticationError(MaxBotError):
    """Raised when authentication fails due to invalid or missing token.

    This typically occurs when:
    - The access token is invalid or expired
    - No access token is provided
    - The token doesn't have sufficient permissions

    Args:
        message: Human-readable error message. Defaults to "Authentication failed. Check your access token."
        code: API error code. Defaults to ERROR_CODE_INVALID_TOKEN.
        response: Raw API response data as a dictionary, if available.
    """

    def __init__(
        self,
        message: str = "Authentication failed. Check your access token.",
        code: Optional[str] = ERROR_CODE_INVALID_TOKEN,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize AuthenticationError with message, code, and response.

        Args:
            message: Human-readable error message. Defaults to "Authentication failed. Check your access token."
            code: API error code. Defaults to ERROR_CODE_INVALID_TOKEN.
            response: Raw API response data as a dictionary, if available.
        """
        super().__init__(message, code, response)


class APIError(MaxBotError):
    """Raised when the API returns an error response.

    This is a general-purpose exception for API errors that don't
    fit into more specific categories like authentication or rate limiting.

    Args:
        message: Human-readable error message describing the API error.
        code: API error code. Defaults to ERROR_CODE_INVALID_REQUEST.
        response: Raw API response data as a dictionary, if available.
    """

    def __init__(
        self, message: str, code: Optional[str] = ERROR_CODE_INVALID_REQUEST, response: Optional[Dict[str, Any]] = None
    ) -> None:
        """Initialize APIError with message, code, and response.

        Args:
            message: Human-readable error message describing the API error.
            code: API error code. Defaults to ERROR_CODE_INVALID_REQUEST.
            response: Raw API response data as a dictionary, if available.
        """
        super().__init__(message, code, response)


class RateLimitError(MaxBotError):
    """Raised when the API rate limit is exceeded.

    This occurs when too many requests are sent in a short time period.
    The client should implement exponential backoff and retry logic.

    Args:
        message: Human-readable error message. Defaults to "Rate limit exceeded. Please try again later."
        code: API error code. Defaults to ERROR_CODE_RATE_LIMIT_EXCEEDED.
        response: Raw API response data as a dictionary, if available.
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please try again later.",
        code: Optional[str] = ERROR_CODE_RATE_LIMIT_EXCEEDED,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize RateLimitError with message, code, and response.

        Args:
            message: Human-readable error message. Defaults to "Rate limit exceeded. Please try again later."
            code: API error code. Defaults to ERROR_CODE_RATE_LIMIT_EXCEEDED.
            response: Raw API response data as a dictionary, if available.
        """
        super().__init__(message, code, response)


class AttachmentNotReadyError(MaxBotError):
    """Raised when an attachment is not ready yet.

    This occurs when an attachment is still being processed by the API.
    The client should wait for the attachment to be ready before sending it.

    Args:
        message: Human-readable error message. Defaults to "Attachment not ready."
        code: API error code. Defaults to ERROR_CODE_ATTACHMENT_NOT_READY.
        response: Raw API response data as a dictionary, if available.
    """

    def __init__(
        self,
        message: str = "Attachment not ready.",
        code: Optional[str] = ERROR_CODE_ATTACHMENT_NOT_READY,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize AttachmentNotReadyError with message, code, and response.

        Args:
            message: Human-readable error message. Defaults to "Attachment not ready."
            code: API error code. Defaults to ERROR_CODE_ATTACHMENT_NOT_READY.
            response: Raw API response data as a dictionary, if available.
        """
        super().__init__(message, code, response)


class ValidationError(MaxBotError):
    """Raised when request validation fails.

    This occurs when the request data doesn't match the API schema,
    such as invalid parameters, missing required fields, or data type mismatches.

    Args:
        message: Human-readable error message describing the validation error.
        code: API error code. Defaults to ERROR_CODE_INVALID_REQUEST.
        response: Raw API response data as a dictionary, if available.
    """

    def __init__(
        self,
        message: str,
        code: Optional[str] = ERROR_CODE_INVALID_REQUEST,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize ValidationError with message, code, and response.

        Args:
            message: Human-readable error message describing the validation error.
            code: API error code. Defaults to ERROR_CODE_INVALID_REQUEST.
            response: Raw API response data as a dictionary, if available.
        """
        super().__init__(message, code, response)


class NotFoundError(MaxBotError):
    """Raised when a requested resource is not found.

    This occurs when trying to access a chat, message, or other resource
    that doesn't exist or the bot doesn't have access to.

    Args:
        message: Human-readable error message. Defaults to "Resource not found."
        code: API error code. Defaults to ERROR_CODE_RESOURCE_NOT_FOUND.
        response: Raw API response data as a dictionary, if available.
    """

    def __init__(
        self,
        message: str = "Resource not found.",
        code: Optional[str] = ERROR_CODE_RESOURCE_NOT_FOUND,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize NotFoundError with message, code, and response.

        Args:
            message: Human-readable error message. Defaults to "Resource not found."
            code: API error code. Defaults to ERROR_CODE_RESOURCE_NOT_FOUND.
            response: Raw API response data as a dictionary, if available.
        """
        super().__init__(message, code, response)


class MethodNotAllowedError(MaxBotError):
    """Raised when an HTTP method is not allowed for the endpoint.

    This occurs when trying to use GET on an endpoint that only accepts POST,
    or similar method/endpoint mismatches.

    Args:
        message: Human-readable error message. Defaults to "Method not allowed for this endpoint."
        code: API error code. Defaults to ERROR_CODE_METHOD_NOT_ALLOWED.
        response: Raw API response data as a dictionary, if available.
    """

    def __init__(
        self,
        message: str = "Method not allowed for this endpoint.",
        code: Optional[str] = ERROR_CODE_METHOD_NOT_ALLOWED,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize MethodNotAllowedError with message, code, and response.

        Args:
            message: Human-readable error message. Defaults to "Method not allowed for this endpoint."
            code: API error code. Defaults to ERROR_CODE_METHOD_NOT_ALLOWED.
            response: Raw API response data as a dictionary, if available.
        """
        super().__init__(message, code, response)


class ServiceUnavailableError(MaxBotError):
    """Raised when the API service is temporarily unavailable.

    This occurs when the API is down for maintenance or experiencing
    temporary issues. The client should retry with exponential backoff.

    Args:
        message: Human-readable error message. Defaults to "Service temporarily unavailable. Please try again later."
        code: API error code. Defaults to ERROR_CODE_SERVICE_UNAVAILABLE.
        response: Raw API response data as a dictionary, if available.
    """

    def __init__(
        self,
        message: str = "Service temporarily unavailable. Please try again later.",
        code: Optional[str] = ERROR_CODE_SERVICE_UNAVAILABLE,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize ServiceUnavailableError with message, code, and response.

        Args:
            message: Human-readable error message. Defaults to "Service temporarily
                unavailable. Please try again later."
            code: API error code. Defaults to ERROR_CODE_SERVICE_UNAVAILABLE.
            response: Raw API response data as a dictionary, if available.
        """
        super().__init__(message, code, response)


class NetworkError(MaxBotError):
    """Raised when network-related errors occur.

    This includes connection timeouts, DNS resolution failures,
    and other network-level issues that prevent communication with the API.

    Args:
        message: Human-readable error message. Defaults to "Network error occurred."
        code: API error code, if available. Defaults to None.
        response: Raw API response data as a dictionary, if available.
    """

    def __init__(
        self,
        message: str = "Network error occurred.",
        code: Optional[str] = None,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize NetworkError with message, code, and response.

        Args:
            message: Human-readable error message. Defaults to "Network error occurred."
            code: API error code, if available. Defaults to None.
            response: Raw API response data as a dictionary, if available.
        """
        super().__init__(message, code, response)


class ConfigurationError(MaxBotError):
    """Raised when there's a configuration error.

    This occurs when the client is misconfigured, such as missing
    required parameters or invalid configuration values.

    Args:
        message: Human-readable error message describing the configuration error.
        code: API error code, if available. Defaults to None.
        response: Raw API response data as a dictionary, if available.
    """

    def __init__(self, message: str, code: Optional[str] = None, response: Optional[Dict[str, Any]] = None) -> None:
        """Initialize ConfigurationError with message, code, and response.

        Args:
            message: Human-readable error message describing the configuration error.
            code: API error code, if available. Defaults to None.
            response: Raw API response data as a dictionary, if available.
        """
        super().__init__(message, code, response)


def parseApiError(statusCode: int, responseData: Dict[str, Any]) -> MaxBotError:
    """Parse API error response and return appropriate exception.

    This function analyzes the HTTP status code and API response data to determine
    the most appropriate exception type to raise. It first checks for specific error
    codes in the response, then falls back to status code mapping.

    Args:
        statusCode: HTTP status code from the API response.
        responseData: Parsed JSON response from API containing error details.

    Returns:
        Appropriate MaxBotError subclass instance based on error code and status.
        Returns specific exceptions like AuthenticationError, RateLimitError, etc.
        when error codes match, otherwise returns a generic APIError.

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
    elif error_code == ERROR_CODE_ATTACHMENT_NOT_READY:
        return AttachmentNotReadyError(error_message, error_code, responseData)

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
