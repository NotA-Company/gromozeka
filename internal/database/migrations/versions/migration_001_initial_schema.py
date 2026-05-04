"""Initial schema migration for the Gromozeka database.

This migration creates all base tables required for the Gromozeka bot system,
extracting table creation logic from the original _initDatabase() method.

The migration creates the following table categories:
- Chat-related tables: chat_messages, chat_settings, chat_users, chat_info,
  chat_stats, chat_user_stats, chat_topics
- Media and attachments: media_attachments
- Task management: delayed_tasks
- User data: user_data
- Spam detection: spam_messages, ham_messages, bayes_tokens, bayes_classes
- Caching: chat_summarization_cache and dynamic cache tables
- Performance indexes for frequently queried columns

This is the first migration (version 1) and establishes the foundational
database schema for the entire application.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration001InitialSchema(BaseMigration):
    """Initial database schema migration for Gromozeka.

    This migration establishes the foundational database schema by creating all
    necessary tables for the bot system. It is the first migration (version 1)
    and should be applied to any new database instance.

    Attributes:
        version: The migration version number (1).
        description: Human-readable description of the migration.
    """

    version: int = 1
    description: str = "Create initial database schema"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create all initial database tables and indexes.

        This method creates the complete initial schema including:
        - Chat-related tables (messages, settings, users, info, stats, topics)
        - Media attachments table
        - Delayed tasks table
        - User data table
        - Spam/ham message tables for Bayes filter training
        - Bayes filter statistics tables (tokens, classes)
        - Chat summarization cache table with index
        - Dynamic cache tables for each CacheType enum value
        - Performance indexes for frequently queried columns

        Args:
            sqlProvider: SQL provider to execute database commands.

        Returns:
            None
        """
        # Import CacheType here to avoid circular dependency
        from ...models import CacheType

        cacheTables: list[ParametrizedQuery] = [ParametrizedQuery(f"""
                CREATE TABLE IF NOT EXISTS cache_{cacheType} (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """) for cacheType in CacheType]

        await sqlProvider.batchExecute(
            [
                # Chat messages table for storing detailed chat message information
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                chat_id INTEGER NOT NULL,
                message_id TEXT NOT NULL,
                date TIMESTAMP NOT NULL,
                user_id INTEGER NOT NULL,
                reply_id TEXT,
                thread_id INTEGER NOT NULL DEFAULT 0,
                root_message_id TEXT,
                message_text TEXT NOT NULL,
                message_type TEXT DEFAULT 'text' NOT NULL,
                message_category TEXT DEFAULT 'user' NOT NULL,
                quote_text TEXT,
                media_id TEXT,
                created_at TIMESTAMP NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            )
        """),
                # Chat-specific settings
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (chat_id, key)
            )
        """),
                # Per-chat known users + some stats (messages count + last seen)
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS chat_users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                full_name TEXT NOT NULL,
                timezone TEXT,
                messages_count INTEGER DEFAULT 0 NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            )
        """),
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS chat_info (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                username TEXT,
                type TEXT NOT NULL,
                is_forum BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """),
                # Chat stats (currently only messages count per date)
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS chat_stats (
                chat_id INTEGER NOT NULL,
                date TIMESTAMP NOT NULL,
                messages_count INTEGER DEFAULT 0 NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (chat_id, date)
            )
        """),
                # Chat user stats (currently only messages count per date)
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS chat_user_stats (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date TIMESTAMP NOT NULL,
                messages_count INTEGER DEFAULT 0 NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (chat_id, user_id, date)
            )
        """),
                # Table with saved Media info
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS media_attachments (
                file_unique_id TEXT PRIMARY KEY,
                file_id TEXT,
                file_size INTEGER,
                media_type TEXT NOT NULL,
                metadata TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                mime_type TEXT,
                local_url TEXT,
                prompt TEXT,
                description TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """),
                # Table for delayed tasks
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS delayed_tasks (
                id TEXT PRIMARY KEY NOT NULL,
                delayed_ts INTEGER NOT NULL,
                function TEXT NOT NULL,
                kwargs TEXT NOT NULL,
                is_done BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """),
                # Some knowledge about user, collected during discussion
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS user_data (
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (user_id, chat_id, key)
            )
        """),
                # Spam messages for learning
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS spam_messages (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message_id TEXT NOT NULL,
                text TEXT NOT NULL,
                reason TEXT NOT NULL,
                score FLOAT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (chat_id, user_id, message_id)
            )
        """),
                # Ham messages for learning
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS ham_messages (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message_id TEXT NOT NULL,
                text TEXT NOT NULL,
                reason TEXT NOT NULL,
                score FLOAT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (chat_id, user_id, message_id)
            )
        """),
                # Chat Topics
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS chat_topics (
                chat_id INTEGER NOT NULL,
                topic_id INTEGER NOT NULL,
                icon_color INTEGER,
                icon_custom_emoji_id TEXT,
                name TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (chat_id, topic_id)
            )
        """),
                # Chat Summarization Cache
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS chat_summarization_cache (
                csid TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                topic_id INTEGER,
                first_message_id TEXT NOT NULL,
                last_message_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """),
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS chat_summarization_cache_ctfl_index
            ON chat_summarization_cache
                (chat_id, topic_id, first_message_id, last_message_id, prompt)
        """),
                # Bayes filter tables for spam detection, dood!
                # Token statistics for Bayes filter
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS bayes_tokens (
                token TEXT NOT NULL,
                chat_id INTEGER,
                spam_count INTEGER DEFAULT 0,
                ham_count INTEGER DEFAULT 0,
                total_count INTEGER DEFAULT 0,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (token, chat_id)
            )
        """),
                # Class statistics for Bayes filter
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS bayes_classes (
                chat_id INTEGER,
                is_spam BOOLEAN NOT NULL,
                message_count INTEGER DEFAULT 0,
                token_count INTEGER DEFAULT 0,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                PRIMARY KEY (chat_id, is_spam)
            )
        """),
                # Indexes for performance
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS bayes_tokens_chat_idx ON bayes_tokens(chat_id)
        """),
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS bayes_tokens_total_idx ON bayes_tokens(total_count)
        """),
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS bayes_classes_chat_idx ON bayes_classes(chat_id)
        """),
            ]
            + cacheTables
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop all tables and indexes created by this migration.

        This method removes all database objects created by the up() method,
        including tables and indexes. It drops cache tables dynamically based
        on the CacheType enum values.

        Args:
            sqlProvider: SQL provider to execute database commands.

        Returns:
            None
        """
        from ...models import CacheType

        tables: list[str] = [
            "chat_messages",
            "chat_settings",
            "chat_users",
            "chat_info",
            "chat_stats",
            "chat_user_stats",
            "media_attachments",
            "delayed_tasks",
            "user_data",
            "spam_messages",
            "ham_messages",
            "chat_topics",
            "chat_summarization_cache",
            "bayes_tokens",
            "bayes_classes",
        ]
        dropTableQueries: list[ParametrizedQuery] = [
            ParametrizedQuery(f"DROP TABLE IF EXISTS {table}") for table in tables
        ]

        dropIndexQueries: list[ParametrizedQuery] = [
            ParametrizedQuery("DROP INDEX IF EXISTS chat_summarization_cache_ctfl_index"),
            ParametrizedQuery("DROP INDEX IF EXISTS bayes_tokens_chat_idx"),
            ParametrizedQuery("DROP INDEX IF EXISTS bayes_tokens_total_idx"),
            ParametrizedQuery("DROP INDEX IF EXISTS bayes_classes_chat_idx"),
        ]

        dropCacheQueries: list[ParametrizedQuery] = [
            ParametrizedQuery(f"DROP TABLE IF EXISTS cache_{cacheType}") for cacheType in CacheType
        ]

        await sqlProvider.batchExecute(dropTableQueries + dropIndexQueries + dropCacheQueries)


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    This function is used by the migration system to dynamically load
    the migration class from this module.

    Returns:
        Type[BaseMigration]: The Migration001InitialSchema class.
    """
    return Migration001InitialSchema
