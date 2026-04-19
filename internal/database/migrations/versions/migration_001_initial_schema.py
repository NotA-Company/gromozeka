"""
Initial schema migration - creates all base tables, dood!

This migration extracts all table creation from the original _initDatabase() method.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration001InitialSchema(BaseMigration):
    """Initial database schema migration, dood!"""

    version = 1
    description = "Create initial database schema"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Create all initial tables, dood!

        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        # Import CacheType here to avoid circular dependency
        from ...models import CacheType

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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, message_id)
            )
        """),
                # Chat-specific settings
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
                # Chat stats (currently only messages count per date)
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS chat_stats (
                chat_id INTEGER NOT NULL,
                date TIMESTAMP NOT NULL,
                messages_count INTEGER DEFAULT 0 NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
                # Some knowledge about user, collected during discussion
                ParametrizedQuery("""
            CREATE TABLE IF NOT EXISTS user_data (
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
            + [
                # Cache tables (for OpenWeatherMap for now)
                ParametrizedQuery(f"""
                CREATE TABLE IF NOT EXISTS cache_{cacheType} (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)
                for cacheType in CacheType
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Drop all tables created by this migration, dood!

        Args:
            cursor: SQLite cursor to execute SQL commands
        """
        from ...models import CacheType

        tables = [
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
        await sqlProvider.batchExecute(
            [
                # Drop all tables in reverse order
                ParametrizedQuery(f"DROP TABLE IF EXISTS {table}")
                for table in tables
            ]
            + [
                # Drop indexes
                ParametrizedQuery("DROP INDEX IF EXISTS chat_summarization_cache_ctfl_index"),
                ParametrizedQuery("DROP INDEX IF EXISTS bayes_tokens_chat_idx"),
                ParametrizedQuery("DROP INDEX IF EXISTS bayes_tokens_total_idx"),
                ParametrizedQuery("DROP INDEX IF EXISTS bayes_classes_chat_idx"),
            ]
            + [
                # Drop cache tables
                ParametrizedQuery(f"DROP TABLE IF EXISTS cache_{cacheType}")
                for cacheType in CacheType
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module, dood!"""
    return Migration001InitialSchema
