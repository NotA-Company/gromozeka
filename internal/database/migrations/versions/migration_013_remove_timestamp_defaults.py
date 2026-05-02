"""
Remove DEFAULT CURRENT_TIMESTAMP from timestamp columns.

This migration removes DEFAULT CURRENT_TIMESTAMP from all timestamp columns
across all tables. Since SQLite does not support ALTER COLUMN to remove defaults,
we must recreate all affected tables using the standard pattern:
1. Create new table without defaults
2. Copy all data from old table
3. Drop old table
4. Rename new table
5. Recreate indexes

This migration affects 19 tables: settings, chat_messages, chat_settings,
chat_users, chat_info, chat_stats, chat_user_stats, media_attachments,
delayed_tasks, user_data, spam_messages, ham_messages, chat_topics,
chat_summarization_cache, bayes_tokens, bayes_classes, cache_storage,
cache, media_groups.

IMPORTANT: This migration includes ALL columns from migrations 2-12 to ensure
no data loss when recreating tables.
"""

from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration


class Migration013RemoveTimestampDefaults(BaseMigration):
    """Remove DEFAULT CURRENT_TIMESTAMP from all timestamp columns."""

    version = 13
    description = "Remove DEFAULT CURRENT_TIMESTAMP from timestamp columns"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Remove DEFAULT CURRENT_TIMESTAMP by recreating tables.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        # Recreate settings table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE settings_new (
                key TEXT PRIMARY KEY,          -- Setting key/identifier
                value TEXT,                    -- Setting value
                created_at TIMESTAMP NOT NULL, -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL  -- Last update timestamp
            )
        """),
                ParametrizedQuery("""
            INSERT INTO settings_new (key, value, created_at, updated_at)
            SELECT key, value, created_at, updated_at FROM settings
        """),
                ParametrizedQuery("DROP TABLE settings"),
                ParametrizedQuery("ALTER TABLE settings_new RENAME TO settings"),
            ]
        )

        # Recreate chat_messages table (includes markup and metadata from migration_007)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_messages_new (
                chat_id INTEGER NOT NULL,                       -- Chat identifier
                message_id TEXT NOT NULL,                       -- Message identifier
                date TIMESTAMP NOT NULL,                        -- Message timestamp
                user_id INTEGER NOT NULL,                       -- User identifier
                reply_id TEXT,                                  -- ID of message being replied to
                thread_id INTEGER NOT NULL DEFAULT 0,           -- Forum topic ID (0 for non-forum chats)
                root_message_id TEXT,                           -- Root message ID for conversation threads
                message_text TEXT NOT NULL,                     -- Message text content
                message_type TEXT DEFAULT 'text' NOT NULL,      -- Type of message (text, photo, video, etc...)
                message_category TEXT DEFAULT 'user' NOT NULL,  -- Message category (user, bot, system, etc...)
                quote_text TEXT,                                -- Quoted text from replied message
                media_id TEXT,                                  -- Foreign key to media_attachments.file_unique_id
                media_group_id TEXT,                            -- Media group identifier for grouped media messages
                markup TEXT DEFAULT "" NOT NULL,                -- JSON-serialized markup
                metadata TEXT DEFAULT "" NOT NULL,              -- JSON-serialized additional metadata
                created_at TIMESTAMP NOT NULL,                  -- Record creation timestamp
                PRIMARY KEY (chat_id, message_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_messages_new (
                chat_id, message_id, date, user_id, reply_id, thread_id,
                root_message_id, message_text, message_type, message_category,
                quote_text, media_id, media_group_id, markup, metadata, created_at
            )
            SELECT chat_id, message_id, date, user_id, reply_id, thread_id,
                   root_message_id, message_text, message_type, message_category,
                   quote_text, media_id, media_group_id, markup, metadata, created_at
            FROM chat_messages
        """),
                ParametrizedQuery("DROP TABLE chat_messages"),
                ParametrizedQuery("ALTER TABLE chat_messages_new RENAME TO chat_messages"),
            ]
        )

        # Recreate chat_settings table (includes updated_by from migration_010)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_settings_new (
                chat_id INTEGER NOT NULL,               -- Chat identifier
                key TEXT NOT NULL,                      -- Setting key/identifier
                value TEXT,                             -- Setting value
                updated_by INTEGER NOT NULL DEFAULT 0,  -- User ID who last updated this setting
                created_at TIMESTAMP NOT NULL,          -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL,          -- Last update timestamp
                PRIMARY KEY (chat_id, key)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_settings_new (chat_id, key, value, updated_by, created_at, updated_at)
            SELECT chat_id, key, value, updated_by, created_at, updated_at FROM chat_settings
        """),
                ParametrizedQuery("DROP TABLE chat_settings"),
                ParametrizedQuery("ALTER TABLE chat_settings_new RENAME TO chat_settings"),
            ]
        )

        # Recreate chat_users table (includes metadata from migration_003, is_spammer removed in migration_009)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_users_new (
                chat_id INTEGER NOT NULL,                   -- Chat identifier
                user_id INTEGER NOT NULL,                   -- User identifier
                username TEXT NOT NULL,                     -- User's @username (with @ sign)
                full_name TEXT NOT NULL,                    -- User's display name
                timezone TEXT,                              -- User's timezone
                messages_count INTEGER DEFAULT 0 NOT NULL,  -- Total messages sent by user in this chat
                metadata TEXT DEFAULT '' NOT NULL,          -- JSON-serialized additional metadata
                created_at TIMESTAMP NOT NULL,              -- First seen timestamp
                updated_at TIMESTAMP NOT NULL,              -- Last activity timestamp
                PRIMARY KEY (chat_id, user_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_users_new (
                chat_id, user_id, username, full_name, timezone,
                messages_count, metadata, created_at, updated_at
            )
            SELECT chat_id, user_id, username, full_name, timezone,
                   messages_count, metadata, created_at, updated_at
            FROM chat_users
        """),
                ParametrizedQuery("DROP TABLE chat_users"),
                ParametrizedQuery("ALTER TABLE chat_users_new RENAME TO chat_users"),
            ]
        )

        # Recreate chat_info table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_info_new (
                chat_id INTEGER PRIMARY KEY,              -- Chat identifier
                title TEXT,                               -- Chat title
                username TEXT,                            -- Chat @username (for public chats)
                type TEXT NOT NULL,                       -- Chat type (private/group/supergroup/channel)
                is_forum BOOLEAN NOT NULL DEFAULT FALSE,  -- Whether chat has forum topics enabled
                created_at TIMESTAMP NOT NULL,            -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL             -- Last update timestamp
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_info_new (
                chat_id, title, username, type, is_forum, created_at, updated_at
            )
            SELECT chat_id, title, username, type, is_forum, created_at, updated_at
            FROM chat_info
        """),
                ParametrizedQuery("DROP TABLE chat_info"),
                ParametrizedQuery("ALTER TABLE chat_info_new RENAME TO chat_info"),
            ]
        )

        # Recreate chat_stats table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_stats_new (
                chat_id INTEGER NOT NULL,                   -- Chat identifier
                date TIMESTAMP NOT NULL,                    -- Date for statistics
                messages_count INTEGER DEFAULT 0 NOT NULL,  -- Total messages count for this date
                created_at TIMESTAMP NOT NULL,              -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL,              -- Last update timestamp
                PRIMARY KEY (chat_id, date)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_stats_new (
                chat_id, date, messages_count, created_at, updated_at
            )
            SELECT chat_id, date, messages_count, created_at, updated_at
            FROM chat_stats
        """),
                ParametrizedQuery("DROP TABLE chat_stats"),
                ParametrizedQuery("ALTER TABLE chat_stats_new RENAME TO chat_stats"),
            ]
        )

        # Recreate chat_user_stats table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_user_stats_new (
                chat_id INTEGER NOT NULL,                   -- Chat identifier
                user_id INTEGER NOT NULL,                   -- User identifier
                date TIMESTAMP NOT NULL,                    -- Date for statistics
                messages_count INTEGER DEFAULT 0 NOT NULL,  -- Total messages count for this date
                created_at TIMESTAMP NOT NULL,              -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL,              -- Last update timestamp
                PRIMARY KEY (chat_id, user_id, date)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_user_stats_new (
                chat_id, user_id, date, messages_count, created_at, updated_at
            )
            SELECT chat_id, user_id, date, messages_count, created_at, updated_at
            FROM chat_user_stats
        """),
                ParametrizedQuery("DROP TABLE chat_user_stats"),
                ParametrizedQuery("ALTER TABLE chat_user_stats_new RENAME TO chat_user_stats"),
            ]
        )

        # Recreate media_attachments table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE media_attachments_new (
                file_unique_id TEXT PRIMARY KEY,         -- Unique file identifier from Telegram
                file_id TEXT,                            -- Telegram file identifier (can change)
                file_size INTEGER,                       -- File size in bytes
                media_type TEXT NOT NULL,                -- Type of media (photo, video, document, etc.)
                metadata TEXT NOT NULL,                  -- JSON-serialized media metadata
                status TEXT NOT NULL DEFAULT 'pending',  -- Processing status (pending, processed, failed)
                mime_type TEXT,                          -- MIME type of the file
                local_url TEXT,                          -- Local storage URL
                prompt TEXT,                             -- AI prompt for media processing
                description TEXT,                        -- AI-generated description
                created_at TIMESTAMP NOT NULL,           -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL            -- Last update timestamp
            )
        """),
                ParametrizedQuery("""
            INSERT INTO media_attachments_new (
                file_unique_id, file_id, file_size, media_type, metadata,
                status, mime_type, local_url, prompt, description,
                created_at, updated_at
            )
            SELECT file_unique_id, file_id, file_size, media_type, metadata,
                   status, mime_type, local_url, prompt, description,
                   created_at, updated_at
            FROM media_attachments
        """),
                ParametrizedQuery("DROP TABLE media_attachments"),
                ParametrizedQuery("ALTER TABLE media_attachments_new RENAME TO media_attachments"),
            ]
        )

        # Recreate delayed_tasks table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE delayed_tasks_new (
                id TEXT PRIMARY KEY NOT NULL,            -- Unique task identifier
                delayed_ts INTEGER NOT NULL,             -- Unix timestamp when task should execute
                function TEXT NOT NULL,                  -- Function name to execute
                kwargs TEXT NOT NULL,                    -- JSON-serialized function arguments
                is_done BOOLEAN NOT NULL DEFAULT FALSE,  -- Task completion status
                created_at TIMESTAMP NOT NULL,           -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL            -- Last update timestamp
            )
        """),
                ParametrizedQuery("""
            INSERT INTO delayed_tasks_new (
                id, delayed_ts, function, kwargs, is_done, created_at, updated_at
            )
            SELECT id, delayed_ts, function, kwargs, is_done, created_at, updated_at
            FROM delayed_tasks
        """),
                ParametrizedQuery("DROP TABLE delayed_tasks"),
                ParametrizedQuery("ALTER TABLE delayed_tasks_new RENAME TO delayed_tasks"),
            ]
        )

        # Recreate user_data table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE user_data_new (
                user_id INTEGER NOT NULL,       -- User identifier
                chat_id INTEGER NOT NULL,       -- Chat identifier
                key TEXT NOT NULL,              -- Data key/identifier
                data TEXT NOT NULL,             -- Data value
                created_at TIMESTAMP NOT NULL,  -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL,  -- Last update timestamp
                PRIMARY KEY (user_id, chat_id, key)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO user_data_new (
                user_id, chat_id, key, data, created_at, updated_at
            )
            SELECT user_id, chat_id, key, data, created_at, updated_at
            FROM user_data
        """),
                ParametrizedQuery("DROP TABLE user_data"),
                ParametrizedQuery("ALTER TABLE user_data_new RENAME TO user_data"),
            ]
        )

        # Recreate spam_messages table (includes confidence from migration_011)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE spam_messages_new (
                chat_id INTEGER NOT NULL,               -- Chat identifier
                user_id INTEGER NOT NULL,               -- User identifier
                message_id TEXT NOT NULL,               -- Message identifier
                text TEXT NOT NULL,                     -- Message text content
                reason TEXT NOT NULL,                   -- Reason for marking as spam
                score FLOAT NOT NULL,                   -- Spam confidence score
                confidence FLOAT NOT NULL DEFAULT 1.0,  -- Classification confidence (0.0-1.0)
                created_at TIMESTAMP NOT NULL,          -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL,          -- Last update timestamp
                PRIMARY KEY (chat_id, user_id, message_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO spam_messages_new (
                chat_id, user_id, message_id, text, reason, score, confidence,
                created_at, updated_at
            )
            SELECT chat_id, user_id, message_id, text, reason, score, confidence,
                   created_at, updated_at
            FROM spam_messages
        """),
                ParametrizedQuery("DROP TABLE spam_messages"),
                ParametrizedQuery("ALTER TABLE spam_messages_new RENAME TO spam_messages"),
            ]
        )

        # Recreate ham_messages table (includes confidence from migration_011)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE ham_messages_new (
                chat_id INTEGER NOT NULL,               -- Chat identifier
                user_id INTEGER NOT NULL,               -- User identifier
                message_id TEXT NOT NULL,               -- Message identifier
                text TEXT NOT NULL,                     -- Message text content
                reason TEXT NOT NULL,                   -- Reason for marking as ham
                score FLOAT NOT NULL,                   -- Ham confidence score
                confidence FLOAT NOT NULL DEFAULT 1.0,  -- Classification confidence (0.0-1.0)
                created_at TIMESTAMP NOT NULL,          -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL,          -- Last update timestamp
                PRIMARY KEY (chat_id, user_id, message_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO ham_messages_new (
                chat_id, user_id, message_id, text, reason, score, confidence,
                created_at, updated_at
            )
            SELECT chat_id, user_id, message_id, text, reason, score, confidence,
                   created_at, updated_at
            FROM ham_messages
        """),
                ParametrizedQuery("DROP TABLE ham_messages"),
                ParametrizedQuery("ALTER TABLE ham_messages_new RENAME TO ham_messages"),
            ]
        )

        # Recreate chat_topics table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_topics_new (
                chat_id INTEGER NOT NULL,       -- Chat identifier
                topic_id INTEGER NOT NULL,      -- Forum topic identifier
                icon_color INTEGER,             -- Topic icon color code
                icon_custom_emoji_id TEXT,      -- Custom emoji icon identifier
                name TEXT,                      -- Topic name
                created_at TIMESTAMP NOT NULL,  -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL,  -- Last update timestamp
                PRIMARY KEY (chat_id, topic_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_topics_new (
                chat_id, topic_id, icon_color, icon_custom_emoji_id,
                name, created_at, updated_at
            )
            SELECT chat_id, topic_id, icon_color, icon_custom_emoji_id,
                   name, created_at, updated_at
            FROM chat_topics
        """),
                ParametrizedQuery("DROP TABLE chat_topics"),
                ParametrizedQuery("ALTER TABLE chat_topics_new RENAME TO chat_topics"),
            ]
        )

        # Recreate chat_summarization_cache table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_summarization_cache_new (
                csid TEXT PRIMARY KEY,           -- Cache entry identifier
                chat_id INTEGER NOT NULL,        -- Chat identifier
                topic_id INTEGER,                -- Forum topic identifier (NULL for main chat)
                first_message_id TEXT NOT NULL,  -- First message ID in summarized range
                last_message_id TEXT NOT NULL,   -- Last message ID in summarized range
                prompt TEXT NOT NULL,            -- AI prompt used for summarization
                summary TEXT NOT NULL,           -- Generated summary text
                created_at TIMESTAMP NOT NULL,   -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL    -- Last update timestamp
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_summarization_cache_new (
                csid, chat_id, topic_id, first_message_id, last_message_id,
                prompt, summary, created_at, updated_at
            )
            SELECT csid, chat_id, topic_id, first_message_id, last_message_id,
                   prompt, summary, created_at, updated_at
            FROM chat_summarization_cache
        """),
                ParametrizedQuery("DROP TABLE chat_summarization_cache"),
                ParametrizedQuery("ALTER TABLE chat_summarization_cache_new RENAME TO chat_summarization_cache"),
                # Recreate index
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS chat_summarization_cache_ctfl_index
            ON chat_summarization_cache
                (chat_id, topic_id, first_message_id, last_message_id, prompt)
        """),
            ]
        )

        # Recreate bayes_tokens table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE bayes_tokens_new (
                token TEXT NOT NULL,            -- Token/word from messages
                chat_id INTEGER,                -- Chat identifier (NULL for global tokens)
                spam_count INTEGER DEFAULT 0,   -- Count of occurrences in spam messages
                ham_count INTEGER DEFAULT 0,    -- Count of occurrences in ham messages
                total_count INTEGER DEFAULT 0,  -- Total count of occurrences
                created_at TIMESTAMP NOT NULL,  -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL,  -- Last update timestamp
                PRIMARY KEY (token, chat_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO bayes_tokens_new (
                token, chat_id, spam_count, ham_count, total_count,
                created_at, updated_at
            )
            SELECT token, chat_id, spam_count, ham_count, total_count,
                   created_at, updated_at
            FROM bayes_tokens
        """),
                ParametrizedQuery("DROP TABLE bayes_tokens"),
                ParametrizedQuery("ALTER TABLE bayes_tokens_new RENAME TO bayes_tokens"),
                # Recreate indexes
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS bayes_tokens_chat_idx ON bayes_tokens(chat_id)
        """),
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS bayes_tokens_total_idx ON bayes_tokens(total_count)
        """),
            ]
        )

        # Recreate bayes_classes table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE bayes_classes_new (
                chat_id INTEGER,                  -- Chat identifier (NULL for global stats)
                is_spam BOOLEAN NOT NULL,         -- Class type (TRUE for spam, FALSE for ham)
                message_count INTEGER DEFAULT 0,  -- Total messages in this class
                token_count INTEGER DEFAULT 0,    -- Total unique tokens in this class
                created_at TIMESTAMP NOT NULL,    -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL,    -- Last update timestamp
                PRIMARY KEY (chat_id, is_spam)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO bayes_classes_new (
                chat_id, is_spam, message_count, token_count,
                created_at, updated_at
            )
            SELECT chat_id, is_spam, message_count, token_count,
                   created_at, updated_at
            FROM bayes_classes
        """),
                ParametrizedQuery("DROP TABLE bayes_classes"),
                ParametrizedQuery("ALTER TABLE bayes_classes_new RENAME TO bayes_classes"),
                # Recreate index
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS bayes_classes_chat_idx ON bayes_classes(chat_id)
        """),
            ]
        )

        # Recreate cache_storage table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE cache_storage_new (
                namespace TEXT NOT NULL,        -- Cache namespace/category
                key TEXT NOT NULL,              -- Cache key
                value TEXT NOT NULL,            -- Cached value
                updated_at TIMESTAMP NOT NULL,  -- Last update timestamp
                PRIMARY KEY (namespace, key)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO cache_storage_new (namespace, key, value, updated_at)
            SELECT namespace, key, value, updated_at FROM cache_storage
        """),
                ParametrizedQuery("DROP TABLE cache_storage"),
                ParametrizedQuery("ALTER TABLE cache_storage_new RENAME TO cache_storage"),
                # Recreate index
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS idx_cache_namespace
            ON cache_storage(namespace)
        """),
            ]
        )

        # Recreate cache table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE cache_new (
                namespace TEXT NOT NULL,        -- Cache namespace/category
                key TEXT NOT NULL,              -- Cache key
                data TEXT NOT NULL,             -- Cached data
                created_at TIMESTAMP NOT NULL,  -- Record creation timestamp
                updated_at TIMESTAMP NOT NULL,  -- Last update timestamp
                PRIMARY KEY (namespace, key)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO cache_new (namespace, key, data, created_at, updated_at)
            SELECT namespace, key, data, created_at, updated_at FROM cache
        """),
                ParametrizedQuery("DROP TABLE cache"),
                ParametrizedQuery("ALTER TABLE cache_new RENAME TO cache"),
                # Recreate indexes
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS idx_cache_namespace_key
            ON cache (namespace, key)
        """),
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS idx_cache_updated_at
            ON cache (updated_at)
        """),
            ]
        )

        # Recreate media_groups table
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE media_groups_new (
                media_group_id TEXT NOT NULL,   -- Media group identifier from Telegram
                media_id TEXT NOT NULL,         -- Individual media identifier
                created_at TIMESTAMP NOT NULL,  -- Record creation timestamp
                PRIMARY KEY (media_group_id, media_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO media_groups_new (media_group_id, media_id, created_at)
            SELECT media_group_id, media_id, created_at FROM media_groups
        """),
                ParametrizedQuery("DROP TABLE media_groups"),
                ParametrizedQuery("ALTER TABLE media_groups_new RENAME TO media_groups"),
            ]
        )

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback by recreating tables WITH DEFAULT CURRENT_TIMESTAMP.

        Args:
            sqlProvider: SQL provider for executing queries

        Returns:
            None
        """
        # Recreate settings table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE settings_new (
                key TEXT PRIMARY KEY,  -- Setting key/identifier
                value TEXT,  -- Setting value
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- Last update timestamp
            )
        """),
                ParametrizedQuery("""
            INSERT INTO settings_new (key, value, created_at, updated_at)
            SELECT key, value, created_at, updated_at FROM settings
        """),
                ParametrizedQuery("DROP TABLE settings"),
                ParametrizedQuery("ALTER TABLE settings_new RENAME TO settings"),
            ]
        )

        # Recreate chat_messages table with defaults (includes markup and metadata from migration_007)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_messages_new (
                chat_id INTEGER NOT NULL,  -- Telegram chat identifier
                message_id TEXT NOT NULL,  -- Telegram message identifier (stored as string)
                date TIMESTAMP NOT NULL,  -- Message timestamp
                user_id INTEGER NOT NULL,  -- Telegram user identifier
                reply_id TEXT,  -- ID of message being replied to
                thread_id INTEGER NOT NULL DEFAULT 0,  -- Forum topic ID (0 for non-forum chats)
                root_message_id TEXT,  -- Root message ID for conversation threads
                message_text TEXT NOT NULL,  -- Message text content
                message_type TEXT DEFAULT 'text' NOT NULL,  -- Type of message (text, photo, video, etc.)
                message_category TEXT DEFAULT 'user' NOT NULL,  -- Message category (user, bot, system)
                quote_text TEXT,  -- Quoted text from replied message
                media_id TEXT,  -- Foreign key to media_attachments.file_unique_id
                media_group_id TEXT,  -- Media group identifier for grouped media messages
                markup TEXT DEFAULT "" NOT NULL,  -- JSON-serialized keyboard markup
                metadata TEXT DEFAULT "" NOT NULL,  -- JSON-serialized additional metadata
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                PRIMARY KEY (chat_id, message_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_messages_new (
                chat_id, message_id, date, user_id, reply_id, thread_id,
                root_message_id, message_text, message_type, message_category,
                quote_text, media_id, media_group_id, markup, metadata, created_at
            )
            SELECT chat_id, message_id, date, user_id, reply_id, thread_id,
                   root_message_id, message_text, message_type, message_category,
                   quote_text, media_id, media_group_id, markup, metadata, created_at
            FROM chat_messages
        """),
                ParametrizedQuery("DROP TABLE chat_messages"),
                ParametrizedQuery("ALTER TABLE chat_messages_new RENAME TO chat_messages"),
            ]
        )

        # Recreate chat_settings table with defaults (includes updated_by from migration_010)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_settings_new (
                chat_id INTEGER NOT NULL,  -- Telegram chat identifier
                key TEXT NOT NULL,  -- Setting key/identifier
                value TEXT,  -- Setting value
                updated_by INTEGER NOT NULL DEFAULT 0,  -- User ID who last updated this setting
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last update timestamp
                PRIMARY KEY (chat_id, key)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_settings_new (chat_id, key, value, updated_by, created_at, updated_at)
            SELECT chat_id, key, value, updated_by, created_at, updated_at FROM chat_settings
        """),
                ParametrizedQuery("DROP TABLE chat_settings"),
                ParametrizedQuery("ALTER TABLE chat_settings_new RENAME TO chat_settings"),
            ]
        )

        # Recreate chat_users table with defaults (includes metadata from migration_003)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_users_new (
                chat_id INTEGER NOT NULL,  -- Telegram chat identifier
                user_id INTEGER NOT NULL,  -- Telegram user identifier
                username TEXT NOT NULL,  -- User's @username (with @ sign)
                full_name TEXT NOT NULL,  -- User's display name
                timezone TEXT,  -- User's timezone (future use)
                messages_count INTEGER DEFAULT 0 NOT NULL,  -- Total messages sent by user in this chat
                metadata TEXT DEFAULT '' NOT NULL,  -- JSON-serialized additional metadata
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- First seen timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last activity timestamp
                PRIMARY KEY (chat_id, user_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_users_new (
                chat_id, user_id, username, full_name, timezone,
                messages_count, metadata, created_at, updated_at
            )
            SELECT chat_id, user_id, username, full_name, timezone,
                   messages_count, metadata, created_at, updated_at
            FROM chat_users
        """),
                ParametrizedQuery("DROP TABLE chat_users"),
                ParametrizedQuery("ALTER TABLE chat_users_new RENAME TO chat_users"),
            ]
        )

        # Recreate chat_info table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_info_new (
                chat_id INTEGER PRIMARY KEY,  -- Telegram chat identifier
                title TEXT,  -- Chat title
                username TEXT,  -- Chat @username (for public chats)
                type TEXT NOT NULL,  -- Chat type (private/group/supergroup/channel)
                is_forum BOOLEAN NOT NULL DEFAULT FALSE,  -- Whether chat has forum topics enabled
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- Last update timestamp
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_info_new (
                chat_id, title, username, type, is_forum, created_at, updated_at
            )
            SELECT chat_id, title, username, type, is_forum, created_at, updated_at
            FROM chat_info
        """),
                ParametrizedQuery("DROP TABLE chat_info"),
                ParametrizedQuery("ALTER TABLE chat_info_new RENAME TO chat_info"),
            ]
        )

        # Recreate chat_stats table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_stats_new (
                chat_id INTEGER NOT NULL,  -- Telegram chat identifier
                date TIMESTAMP NOT NULL,  -- Date for statistics
                messages_count INTEGER DEFAULT 0 NOT NULL,  -- Total messages count for this date
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last update timestamp
                PRIMARY KEY (chat_id, date)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_stats_new (
                chat_id, date, messages_count, created_at, updated_at
            )
            SELECT chat_id, date, messages_count, created_at, updated_at
            FROM chat_stats
        """),
                ParametrizedQuery("DROP TABLE chat_stats"),
                ParametrizedQuery("ALTER TABLE chat_stats_new RENAME TO chat_stats"),
            ]
        )

        # Recreate chat_user_stats table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_user_stats_new (
                chat_id INTEGER NOT NULL,  -- Telegram chat identifier
                user_id INTEGER NOT NULL,  -- Telegram user identifier
                date TIMESTAMP NOT NULL,  -- Date for statistics
                messages_count INTEGER DEFAULT 0 NOT NULL,  -- Total messages count for this date
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last update timestamp
                PRIMARY KEY (chat_id, user_id, date)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_user_stats_new (
                chat_id, user_id, date, messages_count, created_at, updated_at
            )
            SELECT chat_id, user_id, date, messages_count, created_at, updated_at
            FROM chat_user_stats
        """),
                ParametrizedQuery("DROP TABLE chat_user_stats"),
                ParametrizedQuery("ALTER TABLE chat_user_stats_new RENAME TO chat_user_stats"),
            ]
        )

        # Recreate media_attachments table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE media_attachments_new (
                file_unique_id TEXT PRIMARY KEY,  -- Unique file identifier from Telegram
                file_id TEXT,  -- Telegram file identifier (can change)
                file_size INTEGER,  -- File size in bytes
                media_type TEXT NOT NULL,  -- Type of media (photo, video, document, etc.)
                metadata TEXT NOT NULL,  -- JSON-serialized media metadata
                status TEXT NOT NULL DEFAULT 'pending',  -- Processing status (pending, processed, failed)
                mime_type TEXT,  -- MIME type of the file
                local_url TEXT,  -- Local storage URL
                prompt TEXT,  -- AI prompt for media processing
                description TEXT,  -- AI-generated description
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- Last update timestamp
            )
        """),
                ParametrizedQuery("""
            INSERT INTO media_attachments_new (
                file_unique_id, file_id, file_size, media_type, metadata,
                status, mime_type, local_url, prompt, description,
                created_at, updated_at
            )
            SELECT file_unique_id, file_id, file_size, media_type, metadata,
                   status, mime_type, local_url, prompt, description,
                   created_at, updated_at
            FROM media_attachments
        """),
                ParametrizedQuery("DROP TABLE media_attachments"),
                ParametrizedQuery("ALTER TABLE media_attachments_new RENAME TO media_attachments"),
            ]
        )

        # Recreate delayed_tasks table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE delayed_tasks_new (
                id TEXT PRIMARY KEY NOT NULL,  -- Unique task identifier
                delayed_ts INTEGER NOT NULL,  -- Unix timestamp when task should execute
                function TEXT NOT NULL,  -- Function name to execute
                kwargs TEXT NOT NULL,  -- JSON-serialized function arguments
                is_done BOOLEAN NOT NULL DEFAULT FALSE,  -- Task completion status
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- Last update timestamp
            )
        """),
                ParametrizedQuery("""
            INSERT INTO delayed_tasks_new (
                id, delayed_ts, function, kwargs, is_done, created_at, updated_at
            )
            SELECT id, delayed_ts, function, kwargs, is_done, created_at, updated_at
            FROM delayed_tasks
        """),
                ParametrizedQuery("DROP TABLE delayed_tasks"),
                ParametrizedQuery("ALTER TABLE delayed_tasks_new RENAME TO delayed_tasks"),
            ]
        )

        # Recreate user_data table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE user_data_new (
                user_id INTEGER NOT NULL,  -- Telegram user identifier
                chat_id INTEGER NOT NULL,  -- Telegram chat identifier
                key TEXT NOT NULL,  -- Data key/identifier
                data TEXT NOT NULL,  -- Data value
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last update timestamp
                PRIMARY KEY (user_id, chat_id, key)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO user_data_new (
                user_id, chat_id, key, data, created_at, updated_at
            )
            SELECT user_id, chat_id, key, data, created_at, updated_at
            FROM user_data
        """),
                ParametrizedQuery("DROP TABLE user_data"),
                ParametrizedQuery("ALTER TABLE user_data_new RENAME TO user_data"),
            ]
        )

        # Recreate spam_messages table with defaults (includes confidence from migration_011)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE spam_messages_new (
                chat_id INTEGER NOT NULL,  -- Telegram chat identifier
                user_id INTEGER NOT NULL,  -- Telegram user identifier
                message_id TEXT NOT NULL,  -- Telegram message identifier
                text TEXT NOT NULL,  -- Message text content
                reason TEXT NOT NULL,  -- Reason for marking as spam
                score FLOAT NOT NULL,  -- Spam confidence score
                confidence FLOAT NOT NULL DEFAULT 1.0,  -- Classification confidence (0.0-1.0)
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last update timestamp
                PRIMARY KEY (chat_id, user_id, message_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO spam_messages_new (
                chat_id, user_id, message_id, text, reason, score, confidence,
                created_at, updated_at
            )
            SELECT chat_id, user_id, message_id, text, reason, score, confidence,
                   created_at, updated_at
            FROM spam_messages
        """),
                ParametrizedQuery("DROP TABLE spam_messages"),
                ParametrizedQuery("ALTER TABLE spam_messages_new RENAME TO spam_messages"),
            ]
        )

        # Recreate ham_messages table with defaults (includes confidence from migration_011)
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE ham_messages_new (
                chat_id INTEGER NOT NULL,  -- Telegram chat identifier
                user_id INTEGER NOT NULL,  -- Telegram user identifier
                message_id TEXT NOT NULL,  -- Telegram message identifier
                text TEXT NOT NULL,  -- Message text content
                reason TEXT NOT NULL,  -- Reason for marking as ham
                score FLOAT NOT NULL,  -- Ham confidence score
                confidence FLOAT NOT NULL DEFAULT 1.0,  -- Classification confidence (0.0-1.0)
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last update timestamp
                PRIMARY KEY (chat_id, user_id, message_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO ham_messages_new (
                chat_id, user_id, message_id, text, reason, score, confidence,
                created_at, updated_at
            )
            SELECT chat_id, user_id, message_id, text, reason, score, confidence,
                   created_at, updated_at
            FROM ham_messages
        """),
                ParametrizedQuery("DROP TABLE ham_messages"),
                ParametrizedQuery("ALTER TABLE ham_messages_new RENAME TO ham_messages"),
            ]
        )

        # Recreate chat_topics table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_topics_new (
                chat_id INTEGER NOT NULL,  -- Telegram chat identifier
                topic_id INTEGER NOT NULL,  -- Forum topic identifier
                icon_color INTEGER,  -- Topic icon color code
                icon_custom_emoji_id TEXT,  -- Custom emoji icon identifier
                name TEXT,  -- Topic name
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last update timestamp
                PRIMARY KEY (chat_id, topic_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_topics_new (
                chat_id, topic_id, icon_color, icon_custom_emoji_id,
                name, created_at, updated_at
            )
            SELECT chat_id, topic_id, icon_color, icon_custom_emoji_id,
                   name, created_at, updated_at
            FROM chat_topics
        """),
                ParametrizedQuery("DROP TABLE chat_topics"),
                ParametrizedQuery("ALTER TABLE chat_topics_new RENAME TO chat_topics"),
            ]
        )

        # Recreate chat_summarization_cache table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE chat_summarization_cache_new (
                csid TEXT PRIMARY KEY,  -- Cache entry identifier
                chat_id INTEGER NOT NULL,  -- Telegram chat identifier
                topic_id INTEGER,  -- Forum topic identifier (NULL for main chat)
                first_message_id TEXT NOT NULL,  -- First message ID in summarized range
                last_message_id TEXT NOT NULL,  -- Last message ID in summarized range
                prompt TEXT NOT NULL,  -- AI prompt used for summarization
                summary TEXT NOT NULL,  -- Generated summary text
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- Last update timestamp
            )
        """),
                ParametrizedQuery("""
            INSERT INTO chat_summarization_cache_new (
                csid, chat_id, topic_id, first_message_id, last_message_id,
                prompt, summary, created_at, updated_at
            )
            SELECT csid, chat_id, topic_id, first_message_id, last_message_id,
                   prompt, summary, created_at, updated_at
            FROM chat_summarization_cache
        """),
                ParametrizedQuery("DROP TABLE chat_summarization_cache"),
                ParametrizedQuery("ALTER TABLE chat_summarization_cache_new RENAME TO chat_summarization_cache"),
                # Recreate index
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS chat_summarization_cache_ctfl_index
            ON chat_summarization_cache
                (chat_id, topic_id, first_message_id, last_message_id, prompt)
        """),
            ]
        )

        # Recreate bayes_tokens table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE bayes_tokens_new (
                token TEXT NOT NULL,  -- Token/word from messages
                chat_id INTEGER,  -- Telegram chat identifier (NULL for global tokens)
                spam_count INTEGER DEFAULT 0,  -- Count of occurrences in spam messages
                ham_count INTEGER DEFAULT 0,  -- Count of occurrences in ham messages
                total_count INTEGER DEFAULT 0,  -- Total count of occurrences
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last update timestamp
                PRIMARY KEY (token, chat_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO bayes_tokens_new (
                token, chat_id, spam_count, ham_count, total_count,
                created_at, updated_at
            )
            SELECT token, chat_id, spam_count, ham_count, total_count,
                   created_at, updated_at
            FROM bayes_tokens
        """),
                ParametrizedQuery("DROP TABLE bayes_tokens"),
                ParametrizedQuery("ALTER TABLE bayes_tokens_new RENAME TO bayes_tokens"),
                # Recreate indexes
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS bayes_tokens_chat_idx ON bayes_tokens(chat_id)
        """),
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS bayes_tokens_total_idx ON bayes_tokens(total_count)
        """),
            ]
        )

        # Recreate bayes_classes table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE bayes_classes_new (
                chat_id INTEGER,  -- Telegram chat identifier (NULL for global stats)
                is_spam BOOLEAN NOT NULL,  -- Class type (TRUE for spam, FALSE for ham)
                message_count INTEGER DEFAULT 0,  -- Total messages in this class
                token_count INTEGER DEFAULT 0,  -- Total unique tokens in this class
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last update timestamp
                PRIMARY KEY (chat_id, is_spam)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO bayes_classes_new (
                chat_id, is_spam, message_count, token_count,
                created_at, updated_at
            )
            SELECT chat_id, is_spam, message_count, token_count,
                   created_at, updated_at
            FROM bayes_classes
        """),
                ParametrizedQuery("DROP TABLE bayes_classes"),
                ParametrizedQuery("ALTER TABLE bayes_classes_new RENAME TO bayes_classes"),
                # Recreate index
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS bayes_classes_chat_idx ON bayes_classes(chat_id)
        """),
            ]
        )

        # Recreate cache_storage table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE cache_storage_new (
                namespace TEXT NOT NULL,  -- Cache namespace/category
                key TEXT NOT NULL,  -- Cache key
                value TEXT NOT NULL,  -- Cached value
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last update timestamp
                PRIMARY KEY (namespace, key)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO cache_storage_new (namespace, key, value, updated_at)
            SELECT namespace, key, value, updated_at FROM cache_storage
        """),
                ParametrizedQuery("DROP TABLE cache_storage"),
                ParametrizedQuery("ALTER TABLE cache_storage_new RENAME TO cache_storage"),
                # Recreate index
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS idx_cache_namespace
            ON cache_storage(namespace)
        """),
            ]
        )

        # Recreate cache table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE cache_new (
                namespace TEXT NOT NULL,  -- Cache namespace/category
                key TEXT NOT NULL,  -- Cache key
                data TEXT NOT NULL,  -- Cached data
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Last update timestamp
                PRIMARY KEY (namespace, key)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO cache_new (namespace, key, data, created_at, updated_at)
            SELECT namespace, key, data, created_at, updated_at FROM cache
        """),
                ParametrizedQuery("DROP TABLE cache"),
                ParametrizedQuery("ALTER TABLE cache_new RENAME TO cache"),
                # Recreate indexes
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS idx_cache_namespace_key
            ON cache (namespace, key)
        """),
                ParametrizedQuery("""
            CREATE INDEX IF NOT EXISTS idx_cache_updated_at
            ON cache (updated_at)
        """),
            ]
        )

        # Recreate media_groups table with defaults
        await sqlProvider.batchExecute(
            [
                ParametrizedQuery("""
            CREATE TABLE media_groups_new (
                media_group_id TEXT NOT NULL,  -- Media group identifier from Telegram
                media_id TEXT NOT NULL,  -- Individual media identifier
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Record creation timestamp
                PRIMARY KEY (media_group_id, media_id)
            )
        """),
                ParametrizedQuery("""
            INSERT INTO media_groups_new (media_group_id, media_id, created_at)
            SELECT media_group_id, media_id, created_at FROM media_groups
        """),
                ParametrizedQuery("DROP TABLE media_groups"),
                ParametrizedQuery("ALTER TABLE media_groups_new RENAME TO media_groups"),
            ]
        )


def getMigration() -> Type[BaseMigration]:
    """Return the migration class for this module.

    Returns:
        Type[BaseMigration]: The migration class for this module
    """
    return Migration013RemoveTimestampDefaults
