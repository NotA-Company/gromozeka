"""Database wrapper for the Telegram bot.

This module provides the main Database class that serves as the entry point for all
database operations in the Gromozeka bot. It implements a multi-source database
architecture that allows data to be distributed across multiple database backends
(e.g., SQLite, PostgreSQL, MySQL) based on chat-specific routing rules.

The Database class manages:
- Database connections and connection pooling
- Repository initialization for all data models
- Schema migrations and version tracking
- Multi-source data routing and query execution
- Async context management for proper resource cleanup

Key Features:
- Multi-source support: Route different chats to different databases
- Automatic schema migrations: Version-controlled database schema updates
- Repository pattern: Clean separation of data access logic
- Async/await support: Full async/await compatibility for non-blocking operations
- Connection management: Automatic connection pooling and cleanup

Example:
    >>> from internal.database.database import Database
    >>> from internal.database.manager import DatabaseManagerConfig
    >>>
    >>> config = DatabaseManagerConfig(...)
    >>> async with Database(config) as db:
    ...     # Access repositories
    ...     messages = await db.chatMessages.getChatMessagesSince(chatId=123)
    ...     users = await db.chatUsers.getUsers(chatId=123)
"""

import logging
import types
from typing import Optional

from .manager import DatabaseManager, DatabaseManagerConfig
from .migrations import MigrationManager
from .providers import BaseSQLProvider
from .repositories import (
    CacheRepository,
    ChatEmbeddingsRepository,
    ChatInfoRepository,
    ChatMessagesRepository,
    ChatSearchRepository,
    ChatSettingsRepository,
    ChatSummarizationRepository,
    ChatUsersRepository,
    CommonFunctionsRepository,
    DelayedTasksRepository,
    DivinationsRepository,
    EmbeddingModelsRepository,
    MediaAttachmentsRepository,
    SpamRepository,
    UserMemoriesRepository,
    WebhookUpdatesRepository,
)

logger = logging.getLogger(__name__)


class Database:
    """Database wrapper providing a consistent interface for multi-source database operations.

    This class is the main entry point for all database operations in the Gromozeka bot.
    It manages database connections, repositories, and migrations across multiple data
    sources. The class supports both single-source and multi-source configurations with
    automatic schema migration and connection pooling.

    The Database class implements the async context manager protocol, ensuring proper
    resource cleanup when used with async context managers. It initializes all repository
    instances during construction and registers migration hooks to ensure database
    schemas are up-to-date before any operations are performed.

    Attributes:
        manager: Database manager handling connections and multi-source operations.
        common: Repository for common database functions and utilities.
        chatMessages: Repository for chat message storage and retrieval.
        chatEmbeddings: Repository for chat-message embedding provenance
            (writes ``chat_messages.model_id`` and dual-writes vec0) and
            the backfill helper (``getMessagesWithoutEmbeddings``).
            Receives ``embeddingModels.getOrCreateModelId`` as its
            ``modelIdResolver`` per Decision D10.
        chatSearch: Unified chat-message search repository: filter-only
            SQL path and semantic (embedding-based cosine-similarity)
            path, including the public ``searchChatMessages`` dispatcher.
        chatUsers: Repository for chat user management and associations.
        chatSettings: Repository for chat-specific settings and configurations.
        chatInfo: Repository for chat metadata and information.
        chatSummarization: Repository for chat summarization data.
        userMemories: Repository for the unified ``user_memories`` table
            (durable per-(chat, user, thread) facts/bios/events).
        mediaAttachments: Repository for media attachment storage and management.
        spam: Repository for spam detection and filtering data.
        delayedTasks: Repository for delayed task scheduling and management.
        divinations: Repository for tarot/runes divination readings.
        cache: Repository for caching operations.
        webhookUpdates: Repository for Max webhook payload storage and consumption.
        embeddingModels: Repository for the ``models`` embedding-provenance lookup
            table. Constructed first so its bound ``getOrCreateModelId``
            method can be injected as ``modelIdResolver`` into the
            embedding-touching repos (Decision D10 of the
            embedding-model-lookup refactor).
        _migrationManager: Internal migration manager for schema versioning and updates.

    Example:
        >>> from internal.database.database import Database
        >>> from internal.database.manager import DatabaseManagerConfig
        >>>
        >>> config = DatabaseManagerConfig(...)
        >>> async with Database(config) as db:
        ...     # Access repositories
        ...     messages = await db.chatMessages.getChatMessagesSince(chatId=123)
        ...     users = await db.chatUsers.getUsers(chatId=123)
    """

    __slots__ = (
        "manager",
        "common",
        "chatMessages",
        "chatEmbeddings",
        "chatSearch",
        "chatUsers",
        "chatSettings",
        "chatInfo",
        "chatSummarization",
        "userMemories",
        "mediaAttachments",
        "spam",
        "delayedTasks",
        "divinations",
        "cache",
        "webhookUpdates",
        "embeddingModels",
        "_migrationManager",
    )

    manager: DatabaseManager
    """Database manager handling connections and multi-source operations."""

    common: CommonFunctionsRepository
    """Repository for common database functions and utilities."""

    chatMessages: ChatMessagesRepository
    """Repository for chat message storage and retrieval."""

    chatEmbeddings: ChatEmbeddingsRepository
    """Repository for chat-message embedding provenance (writes ``chat_messages.model_id``
    and dual-writes vec0) and the backfill helper (``getMessagesWithoutEmbeddings``).
    Receives ``embeddingModels.getOrCreateModelId`` as its ``modelIdResolver`` per Decision D10."""

    chatSearch: ChatSearchRepository
    """Unified chat-message search: filter-only SQL and semantic vec0 paths,
    with the public ``searchChatMessages`` dispatcher. Receives
    ``embeddingModels.getOrCreateModelId`` as its ``modelIdResolver`` per Decision D10."""

    chatUsers: ChatUsersRepository
    """Repository for chat user management and associations."""

    chatSettings: ChatSettingsRepository
    """Repository for chat-specific settings and configurations."""

    chatInfo: ChatInfoRepository
    """Repository for chat metadata and information."""

    chatSummarization: ChatSummarizationRepository
    """Repository for chat summarization data."""

    userMemories: UserMemoriesRepository
    """Repository for the unified ``user_memories`` store (per-(chat, user, thread)
    facts/preferences/events/relationships/bio; vec0-backed semantic search and
    embedding provenance via the ``models`` lookup). Receives
    ``embeddingModels.getOrCreateModelId`` as its ``modelIdResolver`` per Decision D10."""

    mediaAttachments: MediaAttachmentsRepository
    """Repository for media attachment storage and management."""

    spam: SpamRepository
    """Repository for spam detection and filtering data."""

    delayedTasks: DelayedTasksRepository
    """Repository for delayed task scheduling and management."""

    divinations: DivinationsRepository
    """Repository for tarot/runes divination readings."""

    cache: CacheRepository
    """Repository for caching operations."""

    webhookUpdates: WebhookUpdatesRepository
    """Repository for Max webhook payload storage and consumption."""

    embeddingModels: EmbeddingModelsRepository
    """Repository for the ``models`` embedding-provenance lookup table.
    Constructed first in :meth:`__init__` so its bound
    ``getOrCreateModelId`` method can be injected as the
    ``modelIdResolver`` kwarg into all three embedding-touching repos —
    ``chatEmbeddings``, ``chatSearch``, and ``userMemories`` (Decision
    D10 of the embedding-model-lookup refactor)."""

    _migrationManager: MigrationManager
    """Internal migration manager for schema versioning and updates."""

    def __init__(
        self,
        config: DatabaseManagerConfig,
    ) -> None:
        """Initialize database wrapper with multi-source configuration.

        This constructor initializes the DatabaseManager, creates all repository instances,
        loads migration scripts, and registers the migration hook. The migration hook is
        registered last to ensure all repository tables are created before migrations run.

        Args:
            config: DatabaseManagerConfig containing sources configuration, chat mapping,
                   and default source settings. Defines which database backends to use
                   and how to route queries for different chats.

        Raises:
            Exception: If migration auto-discovery fails when loading migration scripts
                      from the versions directory.
        """
        logger.info("Initializing database")
        self.manager = DatabaseManager(config)

        # Repositories with queries to DB.
        #
        # Construction order matters: ``self.embeddingModels`` MUST be built first
        # because its bound ``getOrCreateModelId`` method is injected as
        # the ``modelIdResolver`` kwarg into every embedding-touching
        # repo (Decision D10 of the embedding-model-lookup refactor —
        # ``docs/plans/embedding-model-lookup-refactor-v1.md`` §8.3).
        # All three embedding-touching repos are wired here:
        # ``self.chatEmbeddings``, ``self.chatSearch``, and
        # ``self.userMemories``.
        self.embeddingModels = EmbeddingModelsRepository(self.manager)
        # Repositories with queries to DB
        self.common = CommonFunctionsRepository(self.manager)
        self.chatMessages = ChatMessagesRepository(self.manager)
        self.chatEmbeddings = ChatEmbeddingsRepository(
            self.manager, modelIdResolver=self.embeddingModels.getOrCreateModelId
        )
        self.chatSearch = ChatSearchRepository(self.manager, modelIdResolver=self.embeddingModels.getOrCreateModelId)
        self.chatUsers = ChatUsersRepository(self.manager)
        self.chatSettings = ChatSettingsRepository(self.manager)
        self.chatInfo = ChatInfoRepository(self.manager)
        self.chatSummarization = ChatSummarizationRepository(self.manager)
        self.userMemories = UserMemoriesRepository(
            self.manager, modelIdResolver=self.embeddingModels.getOrCreateModelId
        )
        self.mediaAttachments = MediaAttachmentsRepository(self.manager)
        self.spam = SpamRepository(self.manager)
        self.delayedTasks = DelayedTasksRepository(self.manager)
        self.divinations = DivinationsRepository(self.manager)
        self.cache = CacheRepository(self.manager)
        self.webhookUpdates = WebhookUpdatesRepository(self.manager)

        self._migrationManager = MigrationManager()
        try:
            self._migrationManager.loadMigrationsFromVersions()
            logger.info("Loaded migrations")
        except Exception as e:
            logger.error(f"Migration auto-discovery failed: {e}")
            raise e

        # This one should be last, so other modules will create it's tables already
        self.manager.addProviderInitializationHook(self.migrateDatabase)

    async def migrateDatabase(self, sqlProvider: BaseSQLProvider, providerName: str, readOnly: bool) -> None:
        """Migrate database schema and run migrations for non-readonly sources.

        This method is called as a provider initialization hook for each database source.
        It creates the settings table for version tracking and executes all pending
        migrations for the specified database provider. The method skips migration for
        read-only sources to prevent accidental schema modifications.

        Connection management is handled automatically by the provider's keepConnection
        parameter. For in-memory databases, keepConnection defaults to True to prevent
        data loss on disconnect. For file-based databases, the provider connects on-demand
        when executing queries.

        The settings table is created first to enable migration version tracking, then
        all pending migrations are executed in order to bring the schema up to date.

        Args:
            sqlProvider: SQL provider instance for database operations. This provider
                        handles the actual SQL execution and connection management.
            providerName: Name of the database provider being migrated. Used for logging
                         and identification purposes.
            readOnly: Whether the provider is in read-only mode. If True, migration is
                     skipped to prevent schema modifications.

        Returns:
            None

        Note:
            This method is automatically called by the DatabaseManager during provider
            initialization. It should not be called directly in normal usage.
        """

        if readOnly:
            logger.debug(f"Skipping DB migration for readonly source {providerName}")
            return

        # Create settings table (needed before migrations for version tracking)
        # Provider will connect automatically via cursor context manager
        await sqlProvider.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)

        # Run migrations for this source
        # Provider manages connections internally based on keepConnection setting
        await self._migrationManager.migrate(sqlProvider=sqlProvider)
        logger.info(f"Database initialization complete for provider '{providerName}'")

    async def __aenter__(self) -> "Database":
        """Enter the async context manager.

        This method enables the Database class to be used as an async context manager,
        ensuring proper resource cleanup when the context is exited. It returns the
        database instance itself, allowing direct access to repositories.

        Returns:
            Database: The database instance itself, enabling access to all repositories and
            database operations.

        Example:
            >>> async with Database(config) as db:
            ...     await db.chatMessages.getMessages(chatId=123)
        """
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[types.TracebackType],
    ) -> None:
        """Exit the async context manager and cleanup all database connections.

        This method is called when exiting the async context manager. It closes all
        database connections managed by the DatabaseManager, ensuring proper resource
        cleanup. If an exception occurred during the context, it logs the error and
        re-raises the exception.

        Args:
            exc_type: Exception type if an exception occurred, or None if no exception
                     occurred during the context.
            exc: Exception instance if an exception occurred, or None.
            tb: Traceback object if an exception occurred, or None.

        Returns:
            None

        Note:
            This method automatically closes all database connections, so explicit
            cleanup is not required when using the async context manager.
        """
        await self.manager.closeAll()
        if exc_type is not None:
            assert exc is not None
            assert tb is not None
            logger.error(f"Exception in database context: {exc_type}", exc_info=(exc_type, exc, tb))
            raise
