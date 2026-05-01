"""
Database wrapper for the Telegram bot.
This wrapper provides an abstraction layer that can be easily replaced
with other database backends in the future.
"""

import logging

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
    TODO: Update docstring
    A wrapper around SQL that provides a consistent interface
    that can be easily replaced with other database backends.
    """

    # _slots__ = ("_connections", "_sources", "_chatMapping", "_locks", "_defaultSource")

    def __init__(
        self,
        config: DatabaseManagerConfig,
    ):
        """
        Initialize database wrapper with single or multi-source configuration, dood!

        Args:
            dbPath: Single database path (legacy mode, mutually exclusive with config)
            maxConnections: Max connections per source (default: 5)
            timeout: Connection timeout in seconds (default: 30.0)
            config: Multi-source config dict with 'sources', 'chatMapping', 'defaultSource'

        Raises:
            ValueError: If neither or both dbPath and config provided
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
        """Migrate database schema and run migrations for all non-readonly sources, dood!"""

        if readOnly:
            logger.debug(f"Skipping DB migration for readonly source {providerName}, dood")
            return

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
