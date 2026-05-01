"""Database repository module.

This module provides repository classes for database operations across different
data domains. Each repository encapsulates database access logic for a specific
entity type (chats, messages, users, etc.) and provides methods for CRUD operations
and domain-specific queries.

All repositories inherit from BaseRepository and require a DatabaseManager instance
for database access.
"""

from .base import BaseRepository
from .cache import CacheRepository
from .chat_info import ChatInfoRepository
from .chat_messages import ChatMessagesRepository
from .chat_settings import ChatSettingsRepository
from .chat_summarization import ChatSummarizationRepository
from .chat_users import ChatUsersRepository
from .common import CommonFunctionsRepository
from .delayed_tasks import DelayedTasksRepository
from .media_attachments import MediaAttachmentsRepository
from .spam import SpamRepository
from .user_data import UserDataRepository

__all__ = [
    "BaseRepository",
    "CacheRepository",
    "ChatInfoRepository",
    "ChatMessagesRepository",
    "ChatSettingsRepository",
    "ChatSummarizationRepository",
    "ChatUsersRepository",
    "CommonFunctionsRepository",
    "DelayedTasksRepository",
    "MediaAttachmentsRepository",
    "SpamRepository",
    "UserDataRepository",
]
