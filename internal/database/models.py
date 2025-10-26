"""
Different DB-related models
"""

from enum import StrEnum
from typing import Optional, TypedDict, Union
import datetime


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
    UNKNOWN = "unknown"

    USER = "user"
    USER_COMMAND = "user-command"

    BOT = "bot"
    BOT_COMMAND_REPLY = "bot-command-reply"
    BOT_ERROR = "bot-error"
    BOT_SUMMARY = "bot-summary"

    BOT_SPAM_NOTIFICATION = "bot-spam-notification"
    USER_SPAM = "user-spam"


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
    message_id: int
    date: datetime.datetime
    user_id: int
    reply_id: Optional[int]
    thread_id: int
    root_message_id: Optional[int]
    message_text: str
    message_type: str
    message_category: Union[str, MessageCategory]
    quote_text: Optional[str]
    media_id: Optional[str]
    created_at: datetime.datetime

    # From User table
    username: str
    full_name: str

    # From Media Info Table
    media_file_unique_id: Optional[str]
    media_file_id: Optional[str]
    media_file_size: Optional[int]
    media_media_type: Optional[str]
    media_metadata: Optional[str]
    media_status: Optional[Union[str, MediaStatus]]
    media_mime_type: Optional[str]
    media_local_url: Optional[str]
    media_prompt: Optional[str]
    media_description: Optional[str]
    media_created_at: Optional[datetime.datetime]
    media_updated_at: Optional[datetime.datetime]


class ChatUserDict(TypedDict):
    # From chat_user table
    chat_id: int
    user_id: int
    username: str
    full_name: str
    timezone: Optional[str]
    messages_count: int
    is_spammer: bool
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

    WEATHER = "weather"  # Weather cache (coordinates -> weather data)
    GEOCODING = "geocoding"  # Geocoding cache (city name -> coordinates)
