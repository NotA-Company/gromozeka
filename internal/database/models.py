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
    created_at: datetime.datetime
    updated_at: datetime.datetime
