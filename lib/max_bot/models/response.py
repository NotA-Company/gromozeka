"""
Response models for Max Messenger Bot API.

This module contains response-related dataclasses including SimpleQueryResult, Error,
Subscription, and other response models for handling API responses.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .common import PaginationInfo


class ResponseStatus(str, Enum):
    """
    Response status enum
    """

    SUCCESS = "success"
    ERROR = "error"
    PENDING = "pending"


class ErrorCode(str, Enum):
    """
    Error code enum
    """

    BAD_REQUEST = "bad_request"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    VALIDATION_ERROR = "validation_error"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONFLICT = "conflict"
    GONE = "gone"
    PRECONDITION_FAILED = "precondition_failed"
    TOO_MANY_REQUESTS = "too_many_requests"


@dataclass(slots=True)
class Error:
    """
    Error model for API error responses
    """

    code: ErrorCode
    """Error code"""
    message: str
    """Error message"""
    details: Optional[Dict[str, Any]] = None
    """Additional error details"""
    request_id: Optional[str] = None
    """Request ID for tracking"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Error":
        """Create Error instance from API response dictionary."""
        return cls(
            code=ErrorCode(data.get("code", "internal_error")),
            message=data.get("message", ""),
            details=data.get("details"),
            request_id=data.get("request_id"),
            api_kwargs={k: v for k, v in data.items() if k not in {"code", "message", "details", "request_id"}},
        )


@dataclass(slots=True)
class SimpleQueryResult:
    """
    Simple query result with success status and optional data
    """

    success: bool
    """Whether the query was successful"""
    data: Optional[Dict[str, Any]] = None
    """Response data"""
    error: Optional[Error] = None
    """Error information if the query failed"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimpleQueryResult":
        """Create SimpleQueryResult instance from API response dictionary."""
        error_data = data.get("error")
        error = None
        if error_data:
            error = Error.from_dict(error_data)

        return cls(
            success=data.get("success", False),
            data=data.get("data"),
            error=error,
            api_kwargs={k: v for k, v in data.items() if k not in {"success", "data", "error"}},
        )


@dataclass(slots=True)
class Subscription:
    """
    Subscription model for bot subscriptions
    """

    id: str
    """Subscription ID"""
    bot_id: int
    """Bot ID"""
    user_id: int
    """User ID"""
    chat_id: Optional[int] = None
    """Chat ID if subscription is for a chat"""
    status: str = "active"
    """Subscription status"""
    created_at: int = 0
    """Creation time in Unix timestamp"""
    updated_at: int = 0
    """Last update time in Unix timestamp"""
    expires_at: Optional[int] = None
    """Expiration time in Unix timestamp"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Subscription":
        """Create Subscription instance from API response dictionary."""
        return cls(
            id=data.get("id", ""),
            bot_id=data.get("bot_id", 0),
            user_id=data.get("user_id", 0),
            chat_id=data.get("chat_id"),
            status=data.get("status", "active"),
            created_at=data.get("created_at", 0),
            updated_at=data.get("updated_at", 0),
            expires_at=data.get("expires_at"),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k not in {"id", "bot_id", "user_id", "chat_id", "status", "created_at", "updated_at", "expires_at"}
            },
        )


@dataclass(slots=True)
class SubscriptionList:
    """
    List of subscriptions
    """

    subscriptions: List[Subscription]
    """Array of subscriptions"""
    pagination: Optional[PaginationInfo] = None
    """Pagination information"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubscriptionList":
        """Create SubscriptionList instance from API response dictionary."""
        subscriptions_data = data.get("subscriptions", [])
        subscriptions = [Subscription.from_dict(sub) for sub in subscriptions_data]

        pagination_data = data.get("pagination")
        pagination = None
        if pagination_data:
            pagination = PaginationInfo.from_dict(pagination_data)

        return cls(
            subscriptions=subscriptions,
            pagination=pagination,
            api_kwargs={k: v for k, v in data.items() if k not in {"subscriptions", "pagination"}},
        )


@dataclass(slots=True)
class WebhookInfo:
    """
    Webhook information
    """

    url: str
    """Webhook URL"""
    secret_token: Optional[str] = None
    """Secret token for webhook verification"""
    max_connections: int = 40
    """Maximum number of concurrent connections"""
    allowed_updates: Optional[List[str]] = None
    """List of allowed update types"""
    last_error: Optional[Error] = None
    """Last webhook error"""
    last_error_date: Optional[int] = None
    """Date of the last webhook error in Unix timestamp"""
    pending_update_count: int = 0
    """Number of updates waiting to be delivered"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebhookInfo":
        """Create WebhookInfo instance from API response dictionary."""
        last_error_data = data.get("last_error")
        last_error = None
        if last_error_data:
            last_error = Error.from_dict(last_error_data)

        return cls(
            url=data.get("url", ""),
            secret_token=data.get("secret_token"),
            max_connections=data.get("max_connections", 40),
            allowed_updates=data.get("allowed_updates"),
            last_error=last_error,
            last_error_date=data.get("last_error_date"),
            pending_update_count=data.get("pending_update_count", 0),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "url",
                    "secret_token",
                    "max_connections",
                    "allowed_updates",
                    "last_error",
                    "last_error_date",
                    "pending_update_count",
                }
            },
        )


@dataclass(slots=True)
class BotStatus:
    """
    Bot status information
    """

    bot_id: int
    """Bot ID"""
    is_active: bool = True
    """Whether the bot is active"""
    webhook_info: Optional[WebhookInfo] = None
    """Webhook information"""
    last_update_date: Optional[int] = None
    """Date of the last update in Unix timestamp"""
    pending_update_count: int = 0
    """Number of updates waiting to be processed"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BotStatus":
        """Create BotStatus instance from API response dictionary."""
        webhook_info_data = data.get("webhook_info")
        webhook_info = None
        if webhook_info_data:
            webhook_info = WebhookInfo.from_dict(webhook_info_data)

        return cls(
            bot_id=data.get("bot_id", 0),
            is_active=data.get("is_active", True),
            webhook_info=webhook_info,
            last_update_date=data.get("last_update_date"),
            pending_update_count=data.get("pending_update_count", 0),
            api_kwargs={
                k: v
                for k, v in data.items()
                if k not in {"bot_id", "is_active", "webhook_info", "last_update_date", "pending_update_count"}
            },
        )


@dataclass(slots=True)
class ApiResponse:
    """
    Generic API response wrapper
    """

    status: ResponseStatus
    """Response status"""
    data: Optional[Dict[str, Any]] = None
    """Response data"""
    error: Optional[Error] = None
    """Error information if the request failed"""
    request_id: Optional[str] = None
    """Request ID for tracking"""
    timestamp: int = 0
    """Response timestamp in Unix time"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApiResponse":
        """Create ApiResponse instance from API response dictionary."""
        error_data = data.get("error")
        error = None
        if error_data:
            error = Error.from_dict(error_data)

        return cls(
            status=ResponseStatus(data.get("status", "success")),
            data=data.get("data"),
            error=error,
            request_id=data.get("request_id"),
            timestamp=data.get("timestamp", 0),
            api_kwargs={
                k: v for k, v in data.items() if k not in {"status", "data", "error", "request_id", "timestamp"}
            },
        )


@dataclass(slots=True)
class ListResponse:
    """
    Generic list response wrapper
    """

    items: List[Dict[str, Any]]
    """List of items"""
    total: int = 0
    """Total number of items"""
    limit: int = 0
    """Number of items per page"""
    offset: int = 0
    """Number of items to skip"""
    has_next: bool = False
    """Whether there are more items"""
    has_prev: bool = False
    """Whether there are previous items"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ListResponse":
        """Create ListResponse instance from API response dictionary."""
        return cls(
            items=data.get("items", []),
            total=data.get("total", 0),
            limit=data.get("limit", 0),
            offset=data.get("offset", 0),
            has_next=data.get("has_next", False),
            has_prev=data.get("has_prev", False),
            api_kwargs={
                k: v for k, v in data.items() if k not in {"items", "total", "limit", "offset", "has_next", "has_prev"}
            },
        )


@dataclass(slots=True)
class CountResponse:
    """
    Generic count response wrapper
    """

    count: int
    """Count of items"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CountResponse":
        """Create CountResponse instance from API response dictionary."""
        return cls(count=data.get("count", 0), api_kwargs={k: v for k, v in data.items() if k not in {"count"}})


@dataclass(slots=True)
class IdResponse:
    """
    Generic ID response wrapper
    """

    id: str
    """ID of the created/updated resource"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IdResponse":
        """Create IdResponse instance from API response dictionary."""
        return cls(id=data.get("id", ""), api_kwargs={k: v for k, v in data.items() if k not in {"id"}})


@dataclass(slots=True)
class BooleanResponse:
    """
    Generic boolean response wrapper
    """

    result: bool
    """Boolean result"""
    api_kwargs: Dict[str, Any] = field(default_factory=dict)
    """Raw API response data"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BooleanResponse":
        """Create BooleanResponse instance from API response dictionary."""
        return cls(result=data.get("result", False), api_kwargs={k: v for k, v in data.items() if k not in {"result"}})
