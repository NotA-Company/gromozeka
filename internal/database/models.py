"""
Different DB-related models
"""

from enum import StrEnum


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
