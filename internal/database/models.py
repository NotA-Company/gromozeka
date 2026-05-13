"""
Database models and type definitions.

This module contains all database-related models, enums, and TypedDict definitions
used throughout the application for representing database entities and their structures.
"""

import datetime
from enum import StrEnum
from typing import Optional, TypedDict, Union

from internal.models import MessageId


class MediaStatus(StrEnum):
    """Status of media attachment processing."""

    NEW = "new"
    """Media is newly created and not yet processed."""
    PENDING = "pending"
    """Media is currently being processed."""
    DONE = "done"
    """Media processing completed successfully."""
    FAILED = "failed"
    """Media processing failed."""


class MessageCategory(StrEnum):
    """Category of a message in the chat system."""

    UNSPECIFIED = "unspecified"
    """Unspecified message category."""

    USER = "user"
    """Message from user."""
    USER_COMMAND = "user-command"
    """Command from user."""

    CHANNEL = "channel"
    """Message from channel/automatic forward."""

    BOT = "bot"
    """Message from bot."""
    BOT_COMMAND_REPLY = "bot-command-reply"
    """Bot reply to command."""
    BOT_ERROR = "bot-error"
    """Bot returned some error."""
    BOT_SUMMARY = "bot-summary"
    """Summary message from bot."""
    BOT_RESENDED = "bot-resended"
    """Bot resended message."""

    BOT_SPAM_NOTIFICATION = "bot-spam-notification"
    """Spam notification message from bot."""
    USER_SPAM = "user-spam"
    """Spam message from user."""

    DELETED = "deleted"
    """Message deleted."""
    USER_CONFIG_ANSWER = "user-config-answer"
    """Answer to some config option."""

    @classmethod
    def fromStr(cls, value: str, default: Optional["MessageCategory"] = None) -> "MessageCategory":
        """Convert string to MessageCategory enum value.

        Args:
            value: String value to convert.
            default: Optional default value to return if conversion fails. If not provided,
                defaults to MessageCategory.UNSPECIFIED.

        Returns:
            MessageCategory enum value, or default if conversion fails and default was
            provided, otherwise MessageCategory.UNSPECIFIED.
        """
        try:
            return cls(value)
        except ValueError:
            if default is None:
                default = MessageCategory.UNSPECIFIED
            return default

    def toRole(self) -> str:
        """Convert message category to role for LLM context.

        Returns:
            "assistant" for bot messages, "user" for all other messages.
        """
        if self.value.startswith("bot"):
            return "assistant"

        return "user"


class SpamReason(StrEnum):
    """Reason for spam classification or action."""

    AUTO = "auto"
    """Automatically detected spam."""
    USER = "user"
    """User reported spam."""
    ADMIN = "admin"
    """Admin marked as spam."""
    UNBAN = "unban"
    """User was unbanned."""


class ChatMessageDict(TypedDict):
    """Dictionary representing a chat message with user information.

    Combines data from chat_message and User tables.
    """

    # From chat_message table
    chat_id: int
    """Chat identifier."""
    message_id: MessageId
    """Message identifier."""
    date: datetime.datetime
    """Message date/time."""
    user_id: int
    """User identifier."""
    reply_id: Optional[MessageId]
    """Replied message identifier."""
    thread_id: int
    """Thread identifier."""
    root_message_id: Optional[MessageId]
    """Root message identifier in thread."""
    message_text: str
    """Message text content."""
    message_type: str
    """Message type."""
    message_category: MessageCategory
    """Message category."""
    quote_text: Optional[str]
    """Quoted text if present."""
    media_id: Optional[str]
    """Media attachment identifier."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    metadata: str
    """JSON metadata."""
    markup: str
    """Message markup."""
    media_group_id: Optional[str]
    """Media group identifier."""

    # From User table
    username: str
    """User username."""
    full_name: str
    """User full name."""


class ChatUserDict(TypedDict):
    """Dictionary representing a user in a chat.

    Data from chat_user table.
    """

    chat_id: int
    """Chat identifier."""
    user_id: int
    """User identifier."""
    username: str
    """User username."""
    full_name: str
    """User full name."""
    timezone: Optional[str]
    """User timezone."""
    messages_count: int
    """Number of messages sent by user."""
    metadata: str
    """JSON metadata."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class ChatInfoDict(TypedDict):
    """Dictionary representing chat information."""

    chat_id: int
    """Chat identifier."""
    title: Optional[str]
    """Chat title."""
    username: Optional[str]
    """Chat username."""
    type: str
    """Chat type."""
    is_forum: bool
    """Whether chat is a forum."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class ChatTopicInfoDict(TypedDict):
    """Dictionary representing a chat topic information."""

    chat_id: int
    """Chat identifier."""
    topic_id: int
    """Topic identifier."""

    icon_color: Optional[int]
    """Topic icon color."""
    icon_custom_emoji_id: Optional[str]
    """Topic custom emoji icon identifier."""
    name: Optional[str]
    """Topic name."""

    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class MediaAttachmentDict(TypedDict):
    """Dictionary representing a media attachment."""

    file_unique_id: str
    """Unique file identifier."""
    file_id: Optional[str]
    """File identifier."""
    file_size: Optional[int]
    """File size in bytes."""
    media_type: str
    """Media type."""
    metadata: str
    """JSON metadata."""
    status: MediaStatus
    """Processing status."""
    mime_type: Optional[str]
    """MIME type."""
    local_url: Optional[str]
    """Local file URL."""
    prompt: Optional[str]
    """Prompt for media generation."""
    description: Optional[str]
    """Media description."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class DelayedTaskDict(TypedDict):
    """Dictionary representing a delayed task."""

    id: str
    """Task identifier."""
    delayed_ts: int
    """Delayed timestamp."""
    function: str
    """Function name to execute."""
    kwargs: str
    """JSON-serialized keyword arguments."""
    is_done: bool
    """Whether task is completed."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class SpamMessageDict(TypedDict):
    """Dictionary representing a spam message record."""

    chat_id: int
    """Chat identifier."""
    user_id: int
    """User identifier."""
    message_id: MessageId
    """Message identifier."""
    text: str
    """Message text."""
    reason: Union[str, SpamReason]
    """Spam reason."""
    score: float
    """Spam score."""
    confidence: float
    """Confidence level."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class ChatSummarizationCacheDict(TypedDict):
    """Dictionary representing a cached chat summarization."""

    csid: str
    """Cache identifier."""
    chat_id: int
    """Chat identifier."""
    topic_id: Optional[int]
    """Topic identifier."""
    first_message_id: MessageId
    """First message identifier in range."""
    last_message_id: MessageId
    """Last message identifier in range."""

    prompt: str
    """Summarization prompt."""
    summary: str
    """Generated summary."""

    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class CacheDict(TypedDict):
    """Weather cache entry from database."""

    key: str
    """Cache key."""
    data: str
    """JSON-serialized response data."""
    created_at: datetime.datetime
    """Record creation timestamp."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class CacheStorageDict(TypedDict):
    """Cache storage entry from cache_storage table."""

    namespace: str
    """Cache namespace."""
    key: str
    """Cache key."""
    value: str
    """Cached value."""
    updated_at: datetime.datetime
    """Record last update timestamp."""


class CacheType(StrEnum):
    """Cache type enum for different cache namespaces."""

    WEATHER = "weather"
    """Weather cache (coordinates -> weather data)."""
    GEOCODING = "geocoding"
    """Geocoding cache (city name -> coordinates)."""
    YANDEX_SEARCH = "yandex_search"
    """Yandex Search API Client cache (request -> Search Result)."""
    URL_CONTENT = "url_content"
    """Cached content of URL (url -> content+contentType)."""
    URL_CONTENT_CONDENSED = "url_content_condensed"
    """Cached condensed content of URL (url+max_size -> content)."""

    # Geocode Maps cache
    GM_SEARCH = "geocode_maps_search"
    """Geocode Maps search cache."""
    GM_REVERSE = "geocode_maps_reverse"
    """Geocode Maps reverse geocoding cache."""
    GM_LOOKUP = "geocode_maps_lookup"
    """Geocode Maps lookup cache."""


class DivinationLayoutDict(TypedDict):
    """Dictionary representing a cached divination layout definition.

    Layouts are cached from external divination APIs to avoid repeated API calls.
    """

    system_id: str
    """Divination system identifier (e.g., 'tarot', 'runes')."""

    layout_id: str
    """Layout name within the system."""

    name_en: str
    """English layout name."""

    name_ru: str
    """Russian layout name."""

    n_symbols: int
    """Number of symbols/positions in the layout."""

    positions: list[str]
    """List of position definitions."""

    description: Optional[str]
    """Optional layout description."""

    created_at: datetime.datetime
    """Record creation timestamp."""

    updated_at: datetime.datetime
    """Record last update timestamp."""
