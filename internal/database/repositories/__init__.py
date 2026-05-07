"""Database repository module, dood!

This module provides repository classes for database operations across different
data domains. Each repository encapsulates database access logic for a specific
entity type (chats, messages, users, etc.) and provides methods for CRUD operations
and domain-specific queries.

All repositories inherit from BaseRepository and require a DatabaseManager instance
for database access.

Key Components:
    BaseRepository: Abstract base class defining the common interface and
        functionality for all repository implementations.
    CacheRepository: Handles cache-related database operations.
    ChatInfoRepository: Manages chat metadata and information.
    ChatMessagesRepository: Handles message storage and retrieval.
    ChatSettingsRepository: Manages chat-specific settings and configurations.
    ChatSummarizationRepository: Handles chat summarization data.
    ChatUsersRepository: Manages user-chat relationships and memberships.
    CommonFunctionsRepository: Provides common database utility functions.
    DelayedTasksRepository: Manages delayed task scheduling and execution.
    DivinationsRepository: Persists tarot/runes divination readings.
    MediaAttachmentsRepository: Handles media attachment storage and metadata.
    SpamRepository: Manages spam detection and filtering data.
    UserDataRepository: Handles user-specific data and preferences.

Usage Example:
    >>> from internal.database.repositories import ChatInfoRepository
    >>> from internal.database.manager import DatabaseManager
    >>>
    >>> db_manager = DatabaseManager()
    >>> chat_repo = ChatInfoRepository(db_manager)
    >>> chat_info = chat_repo.getChatInfo(chat_id=12345)

Architecture:
    The repository pattern implemented here separates data access logic from
    business logic, providing a clean abstraction layer over the database.
    Each repository is responsible for a specific domain entity and provides
    type-safe methods for data manipulation.

Note:
    All repositories require a DatabaseManager instance to be passed during
    initialization. The DatabaseManager handles connection pooling, transaction
    management, and provides access to the underlying database connection.
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
from .divinations import DivinationsRepository
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
    "DivinationsRepository",
    "MediaAttachmentsRepository",
    "SpamRepository",
    "UserDataRepository",
]
