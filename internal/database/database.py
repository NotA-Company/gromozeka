"""
Database wrapper for the Telegram bot.
This wrapper provides an abstraction layer that can be easily replaced
with other database backends in the future.
"""

import logging
from typing import Any

from .manager import DatabaseManager, DatabaseManagerConfig
from .migrations import MigrationManager
from .providers import BaseSQLProvider
from .repositories.cache import CacheRepository
from .repositories.chat_info import ChatInfoRepository
from .repositories.chat_messages import ChatMessagesRepository
from .repositories.chat_settings import ChatSettingsRepository
from .repositories.chat_summarization import ChatSummarizationRepository
from .repositories.chat_users import ChatUsersRepository
from .repositories.common import CommonFunctionsRepository
from .repositories.delayed_tasks import DelayedTasksRepository
from .repositories.media_attachments import MediaAttachmentsRepository
from .repositories.spam import SpamRepository
from .repositories.user_data import UserDataRepository

logger = logging.getLogger(__name__)


class Database:
    """
    Database wrapper providing a consistent interface for multi-source database operations.

    This class manages database connections, repositories, and migrations across multiple
    data sources. It supports both single-source and multi-source configurations with
    automatic schema migration and connection pooling.
    """

    __slots__ = (
        "manager",
        "common",
        "chatMessages",
        "chatUsers",
        "chatSettings",
        "chatInfo",
        "chatSummarization",
        "userData",
        "mediaAttachments",
        "spam",
        "delayedTasks",
        "cache",
        "_migrationManager",
    )

    manager: DatabaseManager
    """Database manager handling connections and multi-source operations."""

    common: CommonFunctionsRepository
    """Repository for common database functions and utilities."""

    chatMessages: ChatMessagesRepository
    """Repository for chat message storage and retrieval."""

    chatUsers: ChatUsersRepository
    """Repository for chat user management and associations."""

    chatSettings: ChatSettingsRepository
    """Repository for chat-specific settings and configurations."""

    chatInfo: ChatInfoRepository
    """Repository for chat metadata and information."""

    chatSummarization: ChatSummarizationRepository
    """Repository for chat summarization data."""

    userData: UserDataRepository
    """Repository for user-specific data and preferences."""

    mediaAttachments: MediaAttachmentsRepository
    """Repository for media attachment storage and management."""

    spam: SpamRepository
    """Repository for spam detection and filtering data."""

    delayedTasks: DelayedTasksRepository
    """Repository for delayed task scheduling and management."""

    cache: CacheRepository
    """Repository for caching operations."""

    _migrationManager: MigrationManager
    """Internal migration manager for schema versioning and updates."""

    def __init__(
        self,
        config: DatabaseManagerConfig,
    ):
        """
        Initialize database wrapper with multi-source configuration.

        Args:
            config: DatabaseManagerConfig containing sources configuration, chat mapping,
                   and default source settings.

        Raises:
            Exception: If migration auto-discovery fails.
        """
        logger.info("Initializing database")
        self.manager = DatabaseManager(config)

        # Repositories with queries to DB
        self.common = CommonFunctionsRepository(self.manager)
        self.chatMessages = ChatMessagesRepository(self.manager)
        self.chatUsers = ChatUsersRepository(self.manager)
        self.chatSettings = ChatSettingsRepository(self.manager)
        self.chatInfo = ChatInfoRepository(self.manager)
        self.chatSummarization = ChatSummarizationRepository(self.manager)
        self.userData = UserDataRepository(self.manager)
        self.mediaAttachments = MediaAttachmentsRepository(self.manager)
        self.spam = SpamRepository(self.manager)
        self.delayedTasks = DelayedTasksRepository(self.manager)
        self.cache = CacheRepository(self.manager)

        self._migrationManager = MigrationManager()
        try:
            self._migrationManager.loadMigrationsFromVersions()
            logger.info("Loaded migrations, dood!")
        except Exception as e:
            logger.error(f"Migration auto-discovery failed: {e}")
            raise e

        # This one should be last, so other modules will create it's tables already
        self.manager.addProviderInitializationHook(self.migrateDatabase)

    async def migrateDatabase(self, sqlProvider: BaseSQLProvider, providerName: str, readOnly: bool) -> None:
        """
        Migrate database schema and run migrations for non-readonly sources.

        Creates the settings table for version tracking and executes all pending
        migrations for the specified database provider.

        Args:
            sqlProvider: SQL provider instance for database operations.
            providerName: Name of the database provider being migrated.
            readOnly: Whether the provider is in read-only mode (skips migration if True).

        Returns:
            None
        """

        if readOnly:
            logger.debug(f"Skipping DB migration for readonly source {providerName}, dood")
            return

        # Ensure connection is open and keep it open during migration
        # This is important for in-memory databases which lose data on disconnect
        await sqlProvider.connect()

        # Create settings table (needed before migrations for version tracking)
        await sqlProvider.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        # Run migrations for this source
        await self._migrationManager.migrate(sqlProvider=sqlProvider)
        logger.info(f"Database initialization complete for provider '{providerName}', dood!")

    async def __aenter__(self) -> "Database":
        """Enter the async context manager.

        Returns:
            The database instance itself.
        """
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Exit the async context manager and cleanup all database connections.

        Args:
            exc_type: Exception type, or None if no exception occurred.
            exc: Exception instance, or None.
            tb: Traceback object, or None.
        """
        await self.manager.closeAll()
        if exc_type is not None:
            logger.error(f"Exception in database context: {exc_type}", exc_info=(exc_type, exc, tb))
            raise
