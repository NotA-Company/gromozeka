"""Max Bot API Constants.

This module contains all constants and enums for the Max Messenger Bot API,
including API configuration, HTTP methods, rate limiting settings, authentication
parameters, content types, API endpoints, and enumerations for text formats,
button types, and attachment types.
"""

from enum import StrEnum
from typing import Final

VERSION: Final[str] = "0.0.1"

# API Configuration
API_BASE_URL: Final[str] = "https://platform-api.max.ru"
# API_BASE_URL: Final[str] = "https://botapi.max.ru"
API_VERSION: Final[str] = "0.0.1"
DEFAULT_TIMEOUT: Final[int] = 30
MAX_RETRIES: Final[int] = 5
RETRY_BACKOFF_FACTOR: Final[float] = 1.0

# HTTP Methods
HTTP_GET: Final[str] = "GET"
HTTP_POST: Final[str] = "POST"
HTTP_PUT: Final[str] = "PUT"
HTTP_DELETE: Final[str] = "DELETE"
HTTP_PATCH: Final[str] = "PATCH"

# API Limits
# MAX_MESSAGE_LENGTH: Final[int] = 4096
MAX_MESSAGE_LENGTH: Final[int] = 4000
MAX_FILE_SIZE: Final[int] = 4 * 1024 * 1024 * 1024  # 4GB
MAX_PHOTOS_PER_MESSAGE: Final[int] = 10
MAX_BUTTONS_PER_ROW: Final[int] = 5
MAX_ROWS_PER_KEYBOARD: Final[int] = 10

# Rate Limiting
DEFAULT_RATE_LIMIT: Final[int] = 100  # requests per second
RATE_LIMIT_WINDOW: Final[int] = 1  # second

# Authentication
ACCESS_TOKEN_PARAM: Final[str] = "access_token"
AUTH_HEADER: Final[str] = "Authorization"

# Content Types
CONTENT_TYPE_JSON: Final[str] = "application/json"
CONTENT_TYPE_FORM_DATA: Final[str] = "multipart/form-data"

# API Endpoints
ENDPOINT_ME: Final[str] = "/me"
ENDPOINT_CHATS: Final[str] = "/chats"
ENDPOINT_MESSAGES: Final[str] = "/messages"
ENDPOINT_SUBSCRIPTIONS: Final[str] = "/subscriptions"
ENDPOINT_UPLOADS: Final[str] = "/uploads"
ENDPOINT_UPDATES: Final[str] = "/updates"
ENDPOINT_ANSWERS: Final[str] = "/answers"


class TextFormat(StrEnum):
    """Text format enum from OpenAPI specification.

    Defines the supported text formatting options for messages sent through
    the Max Messenger Bot API.

    Attributes:
        PLAIN: Plain text without any formatting.
        MARKDOWN: Text formatted using Markdown syntax.
        HTML: Text formatted using HTML tags.
    """

    PLAIN = "plain"
    MARKDOWN = "markdown"
    HTML = "html"


class ButtonType(StrEnum):
    """Button type enum from OpenAPI specification.

    Defines the types of buttons that can be used in inline and reply keyboards.

    Attributes:
        CALLBACK: Button that triggers a callback query when pressed.
        LINK: Button that opens a URL when pressed.
        REQUEST_CONTACT: Button that requests the user's contact information.
        REQUEST_GEO_LOCATION: Button that requests the user's geolocation.
        CHAT: Button that opens a chat with the specified user or group.
        OPEN_APP: Button that opens a specified application.
        REPLY: Button that sends a reply message when pressed.
    """

    CALLBACK = "callback"
    LINK = "link"
    REQUEST_CONTACT = "request_contact"
    REQUEST_GEO_LOCATION = "request_geo_location"
    CHAT = "chat"
    OPEN_APP = "open_app"
    REPLY = "reply"


class AttachmentType(StrEnum):
    """Attachment type enum from OpenAPI specification.

    Defines the types of attachments that can be sent with messages through
    the Max Messenger Bot API.

    Attributes:
        PHOTO: Photo attachment.
        VIDEO: Video attachment.
        AUDIO: Audio attachment.
        FILE: Generic file attachment.
        CONTACT: Contact information attachment.
        STICKER: Sticker attachment.
        SHARE: Share attachment.
        LOCATION: Geolocation attachment.
        INLINE_KEYBOARD: Inline keyboard attachment.
        REPLY_KEYBOARD: Reply keyboard attachment.
        DATA: Data attachment.
    """

    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    CONTACT = "contact"
    STICKER = "sticker"
    SHARE = "share"
    LOCATION = "location"
    INLINE_KEYBOARD = "inline_keyboard"
    REPLY_KEYBOARD = "reply_keyboard"
    DATA = "data"


# Error codes from API specification
ERROR_CODE_INVALID_TOKEN = "verify.token"
ERROR_CODE_INVALID_REQUEST = "invalid.request"
ERROR_CODE_RESOURCE_NOT_FOUND = "resource.not_found"
ERROR_CODE_METHOD_NOT_ALLOWED = "method.not_allowed"
ERROR_CODE_RATE_LIMIT_EXCEEDED = "rate.limit.exceeded"
ERROR_CODE_SERVICE_UNAVAILABLE = "service.unavailable"
ERROR_CODE_ATTACHMENT_NOT_READY = "attachment.not.ready"
