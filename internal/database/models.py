"""
Different DB-related models
"""

import datetime
from enum import StrEnum
from typing import Optional, TypedDict, Union

from internal.models import MessageIdType


class MediaStatus(StrEnum):
    """
    Enum for media status.
    """

    NEW = "new"
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class MessageCategory(StrEnum):
    """
    Enum for message category.
    """

    UNSPECIFIED = "unspecified"
    """Unspecified"""

    USER = "user"
    """Message from user"""
    USER_COMMAND = "user-command"
    """Command from user"""

    CHANNEL = "channel"
    """Message from channel/automatic forward"""

    BOT = "bot"
    """Message from bot"""
    BOT_COMMAND_REPLY = "bot-command-reply"
    """Bot reply to command"""
    BOT_ERROR = "bot-error"
    """Bot returned some error"""
    BOT_SUMMARY = "bot-summary"
    """Summary message from bot"""
    BOT_RESENDED = "bot-resended"
    """Bot resended message"""

    BOT_SPAM_NOTIFICATION = "bot-spam-notification"
    """Spam notification message from bot"""
    USER_SPAM = "user-spam"
    """Spam message from user"""

    DELETED = "deleted"
    """Message deleted"""
    USER_CONFIG_ANSWER = "user-config-answer"
    """Answer to some config option"""

    @classmethod
    def fromStr(cls, value: str, default: Optional["MessageCategory"] = None) -> "MessageCategory":
        try:
            return cls(value)
        except ValueError:
            if default is None:
                default = MessageCategory.UNSPECIFIED
            return default

    def toRole(self) -> str:
        if self.value.startswith("bot"):
            return "assistant"

        return "user"


class SpamReason(StrEnum):
    """
    Enum for spam reason.
    """

    AUTO = "auto"
    USER = "user"
    ADMIN = "admin"
    UNBAN = "unban"


class ChatMessageDict(TypedDict):
    # From chat_message table
    chat_id: int
    message_id: MessageIdType
    date: datetime.datetime
    user_id: int
    reply_id: Optional[MessageIdType]
    thread_id: int
    root_message_id: Optional[MessageIdType]
    message_text: str
    message_type: str
    message_category: Union[str, MessageCategory]
    quote_text: Optional[str]
    media_id: Optional[str]
    created_at: datetime.datetime
    metadata: str
    markup: str
    media_group_id: Optional[str]

    # From User table
    username: str
    full_name: str


class ChatUserDict(TypedDict):
    # From chat_user table
    chat_id: int
    user_id: int
    username: str
    full_name: str
    timezone: Optional[str]
    messages_count: int
    metadata: str
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ChatInfoDict(TypedDict):
    chat_id: int
    title: Optional[str]
    username: Optional[str]
    type: str
    is_forum: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ChatTopicInfoDict(TypedDict):
    chat_id: int
    topic_id: int

    icon_color: Optional[int]
    icon_custom_emoji_id: Optional[str]
    name: Optional[str]

    created_at: datetime.datetime
    updated_at: datetime.datetime


class MediaAttachmentDict(TypedDict):
    file_unique_id: str
    file_id: Optional[str]
    file_size: Optional[int]
    media_type: str
    metadata: str
    status: Union[str, MediaStatus]
    mime_type: Optional[str]
    local_url: Optional[str]
    prompt: Optional[str]
    description: Optional[str]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class DelayedTaskDict(TypedDict):
    id: str
    delayed_ts: int
    function: str
    kwargs: str
    is_done: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SpamMessageDict(TypedDict):
    chat_id: int
    user_id: int
    message_id: int
    text: str
    reason: Union[str, SpamReason]
    score: float
    confidence: float
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ChatSummarizationCacheDict(TypedDict):
    csid: str
    chat_id: int
    topic_id: Optional[int]
    first_message_id: int
    last_message_id: int

    prompt: str
    summary: str

    created_at: datetime.datetime
    updated_at: datetime.datetime


class CacheDict(TypedDict):
    """Weather cache entry from database"""

    key: str
    data: str  # JSON-serialized response
    created_at: datetime.datetime
    updated_at: datetime.datetime


class CacheStorageDict(TypedDict):
    """Cache storage entry from cache_storage table"""

    namespace: str
    key: str
    value: str
    updated_at: datetime.datetime


class CacheType(StrEnum):
    """Cache type enum"""

    WEATHER = "weather"
    """Weather cache (coordinates -> weather data)"""
    GEOCODING = "geocoding"
    """Geocoding cache (city name -> coordinates)"""
    YANDEX_SEARCH = "yandex_search"
    """Yandex Search API Client cache (request-> Search Result)"""
    URL_CONTENT = "url_content"
    """Cached content of URL (url -> content+contentType)"""
    URL_CONTENT_CONDENSED = "url_content_condensed"
    """Cached condensed content of URL (url+max_size -> content)"""

    # Geocode Maps cache
    GM_SEARCH = "geocode_maps_search"
    GM_REVERSE = "geocode_maps_reverse"
    GM_LOOKUP = "geocode_maps_lookup"
