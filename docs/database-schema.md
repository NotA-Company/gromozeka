
# Database Schema Documentation

This document provides comprehensive documentation for the Gromozeka bot's database schema

## Table of Contents

- [Overview](#overview)
- [Multi-Source Architecture](#multi-source-architecture)
- [Migration System](#migration-system)
- [Core Tables](#core-tables)
  - [chat_messages](#chat_messages)
  - [chat_users](#chat_users)
  - [chat_info](#chat_info)
  - [chat_topics](#chat_topics)
  - [chat_settings](#chat_settings)
- [Statistics Tables](#statistics-tables)
  - [chat_stats](#chat_stats)
  - [chat_user_stats](#chat_user_stats)
- [Media Tables](#media-tables)
  - [media_attachments](#media_attachments)
- [User Data Tables](#user-data-tables)
  - [user_data](#user_data)
- [Spam Detection Tables](#spam-detection-tables)
  - [spam_messages](#spam_messages)
  - [ham_messages](#ham_messages)
  - [bayes_tokens](#bayes_tokens)
  - [bayes_classes](#bayes_classes)
- [Cache Tables](#cache-tables)
  - [chat_summarization_cache](#chat_summarization_cache)
  - [cache_storage](#cache_storage)
  - [Dynamic Cache Tables](#dynamic-cache-tables)
- [Task Management Tables](#task-management-tables)
  - [delayed_tasks](#delayed_tasks)
- [Divination Tables](#divination-tables)
  - [divinations](#divinations)
  - [divination_layouts](#divination_layouts)
- [System Tables](#system-tables)
  - [settings](#settings)
- [Enums](#enums)
- [TypedDict Models](#typeddict-models)

---

## Overview

The Gromozeka bot uses SQLite as its database backend with a custom database layer ([`Database`](../internal/database/database.py:1)) that provides:

- **Multi-source database support**: Route different chats to different database files
- **Thread-safe connection pooling**: Per-source thread-local connections
- **Migration system**: Version-controlled schema changes
- **Type-safe data access**: TypedDict models for all database entities
- **Automatic timestamp management**: Created/updated timestamps on all tables

The database stores chat messages, user information, settings, media attachments, spam detection data, and various caches to support the bot's functionality.

---

## Multi-Source Architecture

### Overview

The database supports routing different chats to different SQLite database files. This enables:

- **Data isolation**: Separate databases for different chat groups
- **Performance optimization**: Distribute load across multiple files
- **Backup flexibility**: Independent backup schedules per source
- **Read-only sources**: Support for read-only database replicas

### Configuration

Multi-source configuration is defined in the bot's config file:

```toml
[database]
default = "default"  # Default provider name

[database.providers.default]
provider = "sqlite3"

[database.providers.default.parameters]
dbPath = "data/bot.db"
readOnly = false
timeout = 30
useWal = true

[database.providers.archive]
provider = "sqlite3"

[database.providers.archive.parameters]
dbPath = "data/archive.db"
readOnly = true
timeout = 10
```

### Routing Logic

The database implements 3-tier routing through the repository pattern:

1. **Tier 1 (Highest Priority)**: Explicit `dataSource` parameter
2. **Tier 2 (Medium Priority)**: Chat ID mapping lookup
3. **Tier 3 (Lowest Priority)**: Default source fallback

Example:
```python
# Explicit source routing (Tier 1)
db.chatMessages.getChatMessages(chatId=123, dataSource="archive")

# Chat mapping routing (Tier 2)
db.chatMessages.getChatMessages(chatId=-1001234567890)  # Routes to "archive" via mapping

# Default routing (Tier 3)
db.chatMessages.getChatMessages(chatId=456)  # Routes to "default" source
```

### Read-Only Sources

Sources marked as `readonly = true` will:
- Enable SQLite's `query_only` pragma
- Reject write operations with `ValueError`
- Skip migration execution during initialization

---

## Migration System

### Overview

The migration system ([`MigrationManager`](../internal/database/migrations/manager.py:25)) provides version-controlled database schema changes with:

- **Auto-discovery**: Migrations loaded from [`versions/`](../internal/database/migrations/versions/) directory
- **Version tracking**: Current version stored in [`settings`](#settings) table
- **Sequential execution**: Migrations run in order by version number
- **Rollback support**: Each migration has `up()` and `down()` methods
- **Per-source execution**: Migrations run independently for each non-readonly source

### Migration Files

Migrations are located in [`internal/database/migrations/versions/`](../internal/database/migrations/versions/):

| Version | File | Description |
|---------|------|-------------|
| 1 | [`migration_001_initial_schema.py`](../internal/database/migrations/versions/migration_001_initial_schema.py:1) | Creates all base tables |
| 2 | [`migration_002_add_is_spammer_to_chat_users.py`](../internal/database/migrations/versions/migration_002_add_is_spammer_to_chat_users.py:1) | ~~Adds `is_spammer` column to [`chat_users`](#chat_users)~~ (Reverted by migration_009) |
| 3 | [`migration_003_add_metadata_to_chat_users.py`](../internal/database/migrations/versions/migration_003_add_metadata_to_chat_users.py:1) | Adds `metadata` column to [`chat_users`](#chat_users) |
| 4 | [`migration_004_add_cache_storage_table.py`](../internal/database/migrations/versions/migration_004_add_cache_storage_table.py:1) | Creates [`cache_storage`](#cache_storage) table |
| 5 | [`migration_005_add_yandex_cache.py`](../internal/database/migrations/versions/migration_005_add_yandex_cache.py:1) | Adds Yandex Search cache table |
| 6 | [`migration_006_new_cache_tables.py`](../internal/database/migrations/versions/migration_006_new_cache_tables.py:1) | Adds Geocode Maps cache tables |
| 7 | [`migration_007_messages_metadata.py`](../internal/database/migrations/versions/migration_007_messages_metadata.py:1) | Adds `markup` and `metadata` columns to [`chat_messages`](#chat_messages) |
| 8 | [`migration_008_add_media_group_support.py`](../internal/database/migrations/versions/migration_008_add_media_group_support.py:1) | Adds `media_group_id` column to [`chat_messages`](#chat_messages) and creates [`media_groups`](#media_groups) table |
| 9 | [`migration_009_remove_is_spammer_from_chat_users.py`](../internal/database/migrations/versions/migration_009_remove_is_spammer_from_chat_users.py:1) | Removes `is_spammer` column from [`chat_users`](#chat_users) |
| 10 | [`migration_010_add_updated_by_to_chat_settings.py`](../internal/database/migrations/versions/migration_010_add_updated_by_to_chat_settings.py:1) | Adds `updated_by` column to [`chat_settings`](#chat_settings) |
| 11 | [`migration_011_add_confidence_to_spam_messages.py`](../internal/database/migrations/versions/migration_011_add_confidence_to_spam_messages.py:1) | Adds `confidence` column to [`spam_messages`](#spam_messages) and [`ham_messages`](#ham_messages) |
| 12 | [`migration_012_unify_cache_tables.py`](../internal/database/migrations/versions/migration_012_unify_cache_tables.py:1) | Unifies all cache tables into single [`cache`](#cache) table |
| 13 | [`migration_013_remove_timestamp_defaults.py`](../internal/database/migrations/versions/migration_013_remove_timestamp_defaults.py:1) | Removes `DEFAULT CURRENT_TIMESTAMP` from all timestamp columns |
| 14 | [`migration_014_add_divinations_table.py`](../internal/database/migrations/versions/migration_014_add_divinations_table.py:1) | Creates [`divinations`](#divinations) table and `idx_divinations_user_created` index |
| 15 | [`migration_015_add_divination_layouts_table.py`](../internal/database/migrations/versions/migration_015_add_divination_layouts_table.py:1) | Creates [`divination_layouts`](#divination_layouts) table and `idx_divination_layouts_system` index |

### Creating New Migrations

To create a new migration:

1. Create file: `internal/database/migrations/versions/migration_XXX_description.py`
2. Implement [`BaseMigration`](../internal/database/migrations/base.py:7) class with `version`, `description`, `up()`, and `down()` methods
3. Add `getMigration()` function returning the migration class
4. The migration will be auto-discovered on next startup

Example:
```python
from typing import Type

from ...providers import BaseSQLProvider, ParametrizedQuery
from ..base import BaseMigration

class Migration008AddNewColumn(BaseMigration):
    version = 8
    description = "Add new_column to some_table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        await sqlProvider.execute("""
            ALTER TABLE some_table
            ADD COLUMN new_column TEXT
        """)

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        await sqlProvider.execute("""
            ALTER TABLE some_table
            DROP COLUMN new_column
        """)

def getMigration() -> Type[BaseMigration]:
    return Migration008AddNewColumn
```

---

## Core Tables

### chat_messages

Stores all chat messages with detailed metadata.

**Primary Key**: `(chat_id, message_id)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Telegram chat identifier |
| `message_id` | TEXT | No | - | Telegram message identifier (stored as string) |
| `date` | TIMESTAMP | No | - | Message timestamp |
| `user_id` | INTEGER | No | - | Telegram user identifier |
| `reply_id` | TEXT | Yes | NULL | ID of message being replied to |
| `thread_id` | INTEGER | No | 0 | Forum topic ID (0 for non-forum chats) |
| `root_message_id` | TEXT | Yes | NULL | Root message ID for conversation threads |
| `message_text` | TEXT | No | - | Message text content |
| `message_type` | TEXT | No | 'text' | Type of message (see [`MessageType`](../internal/models.py:1)) |
| `message_category` | TEXT | No | 'user' | Message category (see [`MessageCategory`](#messagecategory)) |
| `quote_text` | TEXT | Yes | NULL | Quoted text from replied message |
| `media_id` | TEXT | Yes | NULL | Foreign key to [`media_attachments.file_unique_id`](#media_attachments) |
| `media_group_id` | TEXT | Yes | NULL | Media group identifier for grouped media messages |
| `markup` | TEXT | No | "" | JSON-serialized keyboard markup |
| `metadata` | TEXT | No | "" | JSON-serialized additional metadata |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |

**Relationships**:
- References [`chat_users`](#chat_users) via `(chat_id, user_id)`
- References [`media_attachments`](#media_attachments) via `media_id`
- References [`media_groups`](#media_groups) via `media_group_id`
- Self-references via `reply_id` and `root_message_id`

**TypedDict**: [`ChatMessageDict`](../internal/database/models.py:67)

**Example Query**:
```python
# Get recent messages from a chat
messages = db.chatMessages.getChatMessagesSince(
    chatId=-1001234567890,
    sinceDateTime=datetime.now() - timedelta(hours=24),
    limit=100
)
```

---

### chat_users

Stores per-chat user information and statistics.

**Primary Key**: `(chat_id, user_id)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Telegram chat identifier |
| `user_id` | INTEGER | No | - | Telegram user identifier |
| `username` | TEXT | No | - | User's @username (with @ sign) |
| `full_name` | TEXT | No | - | User's display name |
| `timezone` | TEXT | Yes | NULL | User's timezone (future use) |
| `messages_count` | INTEGER | No | 0 | Total messages sent by user in this chat |
| `metadata` | TEXT | No | "" | JSON-serialized additional metadata |
| `created_at` | TIMESTAMP | No | - | First seen timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last activity timestamp (must be provided explicitly) |

**Relationships**:
- Referenced by [`chat_messages`](#chat_messages) via `(chat_id, user_id)`
- Referenced by [`user_data`](#user_data) via `(chat_id, user_id)`

**TypedDict**: [`ChatUserDict`](../internal/database/models.py:104)

**Example Query**:
```python
# Get user info
user = db.chatUsers.getChatUser(chatId=-1001234567890, userId=123456789)
if user:
    print(f"{user['full_name']} (@{user['username']})")
    print(f"Messages: {user['messages_count']}")
```

---

### chat_info

Stores chat metadata and configuration.

**Primary Key**: `chat_id`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Telegram chat identifier |
| `title` | TEXT | Yes | NULL | Chat title |
| `username` | TEXT | Yes | NULL | Chat @username (for public chats) |
| `type` | TEXT | No | - | Chat type (private/group/supergroup/channel) |
| `is_forum` | BOOLEAN | No | FALSE | Whether chat has forum topics enabled |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**TypedDict**: [`ChatInfoDict`](../internal/database/models.py:118)

**Example Query**:
```python
# Get chat info
chat = db.chatInfo.getChatInfo(chatId=-1001234567890)
if chat and chat['is_forum']:
    topics = db.chatTopics.getChatTopics(chatId=chat['chat_id'])
```

---

### chat_topics

Stores forum topic information for chats with topics enabled.

**Primary Key**: `(chat_id, topic_id)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Telegram chat identifier |
| `topic_id` | INTEGER | No | - | Forum topic identifier |
| `icon_color` | INTEGER | Yes | NULL | Topic icon color |
| `icon_custom_emoji_id` | TEXT | Yes | NULL | Custom emoji ID for topic icon |
| `name` | TEXT | Yes | NULL | Topic name |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Relationships**:
- References [`chat_info`](#chat_info) via `chat_id`

**TypedDict**: [`ChatTopicInfoDict`](../internal/database/models.py:128)

---

### chat_settings

Stores per-chat configuration settings.

**Primary Key**: `(chat_id, key)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Telegram chat identifier |
| `key` | TEXT | No | - | Setting key (see [`ChatSettingsKey`](../internal/bot/models/chat_settings.py:41)) |
| `value` | TEXT | Yes | NULL | Setting value (stored as string) |
| `updated_by` | INTEGER | No | - | User ID who last updated the setting |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Available Settings**: See [`ChatSettingsKey`](../internal/bot/models/chat_settings.py:41) enum for all available settings including:
- LLM model selection (`chat-model`, `summary-model`, etc.)
- Prompts (`chat-prompt`, `summary-prompt`, etc.)
- Feature flags (`use-tools`, `parse-images`, `detect-spam`, etc.)
- Spam detection thresholds
- Bayes filter configuration

**Example Query**:
```python
# Get chat settings
settings = db.chatSettings.getChatSettings(chatId=-1001234567890)
# Returns Dict[str, tuple[str, int]] where tuple is (value, updated_by)
chatModel = settings.get('chat-model', ('gpt-4', 0))[0]  # Index [0] for value

# Set a setting (updatedBy is REQUIRED)
db.chatSettings.setChatSetting(
    chatId=-1001234567890,
    key='parse-images',
    value='true',
    updatedBy=userId  # Required keyword-only argument
)
```

---

## Statistics Tables

### chat_stats

Aggregated daily statistics per chat.

**Primary Key**: `(chat_id, date)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Telegram chat identifier |
| `date` | TIMESTAMP | No | - | Date (time set to 00:00:00) |
| `messages_count` | INTEGER | No | 0 | Total messages sent on this date |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Note**: Automatically updated when messages are saved via repository methods.

---

### chat_user_stats

Aggregated daily statistics per user per chat.

**Primary Key**: `(chat_id, user_id, date)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Telegram chat identifier |
| `user_id` | INTEGER | No | - | Telegram user identifier |
| `date` | TIMESTAMP | No | - | Date (time set to 00:00:00) |
| `messages_count` | INTEGER | No | 0 | Messages sent by user on this date |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Note**: Automatically updated when messages are saved via repository methods.

---

## Media Tables

### media_groups

Stores media group relationships for messages with multiple media items sent together.

**Primary Key**: `(media_group_id, media_id)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `media_group_id` | TEXT | No | - | Telegram media group identifier |
| `media_id` | TEXT | No | - | Foreign key to [`media_attachments.file_unique_id`](#media_attachments) |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Relationships**:
- References [`media_attachments`](#media_attachments) via `media_id`
- Referenced by [`chat_messages`](#chat_messages) via `media_group_id`

**Note**: Media groups allow tracking multiple media items (photos, videos, documents) sent together in a single message or album.

---

### media_attachments

Stores information about media attachments (images, documents, etc.).

**Primary Key**: `file_unique_id`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `file_unique_id` | TEXT | No | - | Telegram's unique file identifier |
| `file_id` | TEXT | Yes | NULL | Telegram's file identifier (can change) |
| `file_size` | INTEGER | Yes | NULL | File size in bytes |
| `media_type` | TEXT | No | - | Type of media (photo/document/video/etc.) |
| `metadata` | TEXT | No | - | JSON-serialized media metadata |
| `status` | TEXT | No | 'pending' | Processing status (see [`MediaStatus`](#mediastatus)) |
| `mime_type` | TEXT | Yes | NULL | MIME type of the file |
| `local_url` | TEXT | Yes | NULL | Local file path if downloaded |
| `prompt` | TEXT | Yes | NULL | Prompt used for image generation |
| `description` | TEXT | Yes | NULL | AI-generated description of media |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Relationships**:
- Referenced by [`chat_messages`](#chat_messages) via `media_id`

**TypedDict**: [`MediaAttachmentDict`](../internal/database/models.py:140)

---

## User Data Tables

### user_data

Stores arbitrary key-value data about users collected during conversations.

**Primary Key**: `(user_id, chat_id, key)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `user_id` | INTEGER | No | - | Telegram user identifier |
| `chat_id` | INTEGER | No | - | Telegram chat identifier |
| `key` | TEXT | No | - | Data key |
| `data` | TEXT | No | - | Data value |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Example**: Store user preferences, facts mentioned in conversation, etc.

```python
# Store user data
db.userData.addUserData(userId=123, chatId=-1001234567890, key='favorite_color', data='blue')

# Retrieve user data
userData = db.userData.getUserData(userId=123, chatId=-1001234567890)
favoriteColor = userData.get('favorite_color')
```

---

## Spam Detection Tables

### spam_messages

Stores messages identified as spam for training and analysis.

**Primary Key**: `(chat_id, user_id, message_id)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Telegram chat identifier |
| `user_id` | INTEGER | No | - | Telegram user identifier |
| `message_id` | TEXT | No | - | Telegram message identifier |
| `text` | TEXT | No | - | Message text content |
| `reason` | TEXT | No | - | Reason for spam classification (see [`SpamReason`](#spamreason)) |
| `score` | FLOAT | No | - | Spam confidence score (0-100) |
| `confidence` | FLOAT | No | 1.0 | Detection confidence level (0-1) |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**TypedDict**: [`SpamMessageDict`](../internal/database/models.py:165)

---

### ham_messages

Stores legitimate (non-spam) messages for training spam filters.

**Primary Key**: `(chat_id, user_id, message_id)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Telegram chat identifier |
| `user_id` | INTEGER | No | - | Telegram user identifier |
| `message_id` | TEXT | No | - | Telegram message identifier |
| `text` | TEXT | No | - | Message text content |
| `reason` | TEXT | No | - | Reason for ham classification |
| `score` | FLOAT | No | - | Confidence score |
| `confidence` | FLOAT | No | 1.0 | Detection confidence level (0-1) |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

---

### bayes_tokens

Stores token statistics for Bayesian spam filtering.

**Primary Key**: `(token, chat_id)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `token` | TEXT | No | - | Token (word or n-gram) |
| `chat_id` | INTEGER | Yes | NULL | Chat identifier (NULL for global stats) |
| `spam_count` | INTEGER | No | 0 | Occurrences in spam messages |
| `ham_count` | INTEGER | No | 0 | Occurrences in ham messages |
| `total_count` | INTEGER | No | 0 | Total occurrences |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Indexes**:
- `bayes_tokens_chat_idx` on `chat_id`
- `bayes_tokens_total_idx` on `total_count`

---

### bayes_classes

Stores class statistics for Bayesian spam filtering.

**Primary Key**: `(chat_id, is_spam)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | Yes | NULL | Chat identifier (NULL for global stats) |
| `is_spam` | BOOLEAN | No | - | Whether this is spam class (TRUE) or ham class (FALSE) |
| `message_count` | INTEGER | No | 0 | Number of messages in this class |
| `token_count` | INTEGER | No | 0 | Total tokens in this class |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Indexes**:
- `bayes_classes_chat_idx` on `chat_id`

---

## Cache Tables

### chat_summarization_cache

Caches chat message summaries to avoid regenerating them.

**Primary Key**: `csid`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `csid` | TEXT | No | - | Cache ID (SHA512 hash of cache key) |
| `chat_id` | INTEGER | No | - | Telegram chat identifier |
| `topic_id` | INTEGER | Yes | NULL | Forum topic identifier |
| `first_message_id` | TEXT | No | - | First message ID in summarized range |
| `last_message_id` | TEXT | No | - | Last message ID in summarized range |
| `prompt` | TEXT | No | - | Summarization prompt used |
| `summary` | TEXT | No | - | Generated summary |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Indexes**:
- `chat_summarization_cache_ctfl_index` on `(chat_id, topic_id, first_message_id, last_message_id, prompt)`

**TypedDict**: [`ChatSummarizationCacheDict`](../internal/database/models.py:176)

**Cache Key Generation**: Implemented in the chatMessages repository

---

### cache_storage

Generic key-value cache storage with namespace support.

**Primary Key**: `(namespace, key)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `namespace` | TEXT | No | - | Cache namespace for organization |
| `key` | TEXT | No | - | Cache key |
| `value` | TEXT | No | - | Cached value (JSON-serialized) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**TypedDict**: [`CacheStorageDict`](../internal/database/models.py:199)

---

### cache

Unified cache table for all cache types (replaces separate cache tables from migration_012).

**Primary Key**: `(namespace, key)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `namespace` | TEXT | No | - | Cache namespace (e.g., 'weather', 'geocoding', 'yandex_search') |
| `key` | TEXT | No | - | Cache key |
| `data` | TEXT | No | - | Cached data (JSON-serialized) |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Indexes**:
- `idx_cache_namespace_key` on `(namespace, key)`
- `idx_cache_updated_at` on `updated_at` (for TTL cleanup)

**TypedDict**: [`CacheDict`](../internal/database/models.py:190)

**Available Namespaces**: See [`CacheType`](#cachetype) enum for all available cache namespaces including:
- `WEATHER` - Weather API responses
- `GEOCODING` - Geocoding API responses
- `YANDEX_SEARCH` - Yandex Search API responses
- `GM_SEARCH` - Geocode Maps search results
- `GM_REVERSE` - Geocode Maps reverse geocoding
- `GM_LOOKUP` - Geocode Maps location lookups

---

## Task Management Tables

### delayed_tasks

Stores tasks scheduled for delayed execution.

**Primary Key**: `id`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | TEXT | No | - | Unique task identifier |
| `delayed_ts` | INTEGER | No | - | Unix timestamp when task should execute |
| `function` | TEXT | No | - | Function name to execute |
| `kwargs` | TEXT | No | - | JSON-serialized function arguments |
| `is_done` | BOOLEAN | No | FALSE | Whether task has been executed |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**TypedDict**: [`DelayedTaskDict`](../internal/database/models.py:155)

---

## Divination Tables

### divinations

Stores tarot and rune readings produced by `DivinationHandler` (see [`internal/bot/common/handlers/divination.py`](../internal/bot/common/handlers/divination.py:1)). One row per reading, keyed off the originating `/taro` / `/runes` user-command message — same composite-PK pattern as [`chat_messages`](#chat_messages)

**Primary Key**: `(chat_id, message_id)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Chat identifier where the reading was requested |
| `message_id` | TEXT | No | - | ID of the user command message that triggered the reading |
| `user_id` | INTEGER | No | - | User who requested the reading |
| `system_id` | TEXT | No | - | Divination system (`tarot`, `runes`) |
| `deck_id` | TEXT | No | - | Deck identifier (e.g. `rws`, `elder_futhark`) |
| `layout_id` | TEXT | No | - | Layout identifier (e.g. `three_card`, `celtic_cross`, `three_runes`) |
| `question` | TEXT | No | `''` | User's question (may be empty) |
| `draws_json` | TEXT | No | - | JSON-serialized list of drawn symbols with positions and reversed flags |
| `interpretation` | TEXT | No | `''` | LLM-generated interpretation of the reading |
| `image_prompt` | TEXT | Yes | NULL | Image prompt sent to image generator (when `image-generation = true`) |
| `invoked_via` | TEXT | No | - | Either `'command'` (slash command) or `'llm_tool'` |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |

**Indexes**:
- `idx_divinations_user_created` on `(chat_id, user_id, created_at)` — for "recent readings by user" queries

**Note**: Uses the same composite-PK convention as [`chat_messages`](#chat_messages). This table has no foreign-key relationships to other tables; image media is resolved via the normal message-history pipeline. Created by `migration_014`; only populated when `[divination] enabled = true`. See [`docs/llm/configuration.md`](llm/configuration.md) for feature config.

---

### divination_layouts

Caches layout definitions discovered via LLM for reuse in divination readings.

**Primary Key**: `(system_id, layout_id)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `system_id` | TEXT | No | - | Divination system (`tarot`, `runes`) |
| `layout_id` | TEXT | No | - | Machine-readable layout identifier |
| `name_en` | TEXT | No | - | English name (source of truth) |
| `name_ru` | TEXT | No | - | Russian display name |
| `n_symbols` | INTEGER | No | - | Number of positions in the layout |
| `positions` | TEXT | No | - | JSON-serialized array of position definitions |
| `description` | TEXT | Yes | NULL | Layout description |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Indexes**:
- `idx_divination_layouts_system` on `system_id`

**Negative Cache Pattern**: Failed layout discoveries are stored as negative cache entries:
- `name_en` set to empty string (`''`)
- `n_symbols` set to `0`
- This prevents repeated failed discovery attempts for the same layout

**Usage Examples**:
```python
from internal.database.repositories import DivinationLayoutsRepository

# Get a layout from cache
repo = DivinationLayoutsRepository(db.manager)
layout = await repo.getLayout(systemId='tarot', layoutId='three_card')

# Save a discovered layout
await repo.saveLayout(
    systemId='tarot',
    layoutId='three_card',
    nameEn='Three Card Spread',
    nameRu='Расклад на три карты',
    nSymbols=3,
    positions=json.dumps([
        {'name': 'Past', 'description': 'Past events'},
        {'name': 'Present', 'description': 'Current situation'},
        {'name': 'Future', 'description': 'Future outcome'}
    ]),
    description='Simple three-card spread for time-based readings'
)

# Negative cache pattern for failed discovery
await repo.saveLayout(
    systemId='tarot',
    layoutId='unknown_layout',
    nameEn='',  # Empty indicates negative cache
    nameRu='',
    nSymbols=0,  # Zero indicates negative cache
    positions='[]',
    description=None
)
```

**Note**: Created by `migration_015`. This table caches layout definitions discovered through LLM and web search to avoid repeated API calls. Only populated when `[divination] enabled = true` and layout discovery is used.

---

## System Tables

### settings

Stores global system settings and migration version tracking.

**Primary Key**: `key`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `key` | TEXT | No | - | Setting key |
| `value` | TEXT | Yes | NULL | Setting value |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Special Keys**:
- `db-migration-version` - Current migration version number
- `db-migration-last-run` - ISO timestamp of last migration run

---

## Enums

### MessageCategory

Categorizes messages by their source and purpose.

**Defined in**: [`internal/database/models.py:23`](../internal/database/models.py:23)

| Value | Description |
|-------|-------------|
| `UNSPECIFIED` | Unspecified category |
| `USER` | Regular message from user |
| `USER_COMMAND` | Command from user |
| `CHANNEL` | Message from channel/automatic forward |
| `BOT` | Regular message from bot |
| `BOT_COMMAND_REPLY` | Bot reply to command |
| `BOT_ERROR` | Bot error message |
| `BOT_SUMMARY` | Summary message from bot |
| `BOT_RESENDED` | Bot resent message |
| `BOT_SPAM_NOTIFICATION` | Spam notification from bot |
| `USER_SPAM` | Spam message from user |

---

### MediaStatus

Tracks media processing status.

**Defined in**: [`internal/database/models.py:12`](../internal/database/models.py:12)

| Value | Description |
|-------|-------------|
| `NEW` | Newly received, not yet processed |
| `PENDING` | Processing in progress |
| `DONE` | Processing completed successfully |
| `FAILED` | Processing failed |

---

### SpamReason

Indicates why a message was marked as spam.

**Defined in**: [`internal/database/models.py:56`](../internal/database/models.py:56)

| Value | Description |
|-------|-------------|
| `AUTO` | Automatically detected as spam |
| `USER` | Marked as spam by regular user |
| `ADMIN` | Marked as spam by admin |
| `UNBAN` | User unbanned (spam marking removed) |

---

### CacheType

Defines available cache types for dynamic cache tables.

**Defined in**: [`internal/database/models.py:208`](../internal/database/models.py:208)

| Value | Description |
|-------|-------------|
| `WEATHER` | Weather API cache |
| `GEOCODING` | Geocoding API cache |
| `YANDEX_SEARCH` | Yandex Search API cache |
| `GM_SEARCH` | Geocode Maps search cache |
| `GM_REVERSE` | Geocode Maps reverse geocoding cache |
| `GM_LOOKUP` | Geocode Maps lookup cache |

---

## TypedDict Models

All database queries return strongly-typed dictionaries defined in [`internal/database/models.py`](../internal/database/models.py:1):

| TypedDict | Description | Definition |
|-----------|-------------|------------|
| [`ChatMessageDict`](../internal/database/models.py:67) | Chat message with user and media info | Lines 67-102 |
| [`ChatUserDict`](../internal/database/models.py:104) | Chat user information | Lines 104-116 |
| [`ChatInfoDict`](../internal/database/models.py:118) | Chat metadata | Lines 118-126 |
| [`ChatTopicInfoDict`](../internal/database/models.py:128) | Forum topic information | Lines 128-138 |
| [`MediaAttachmentDict`](../internal/database/models.py:140) | Media attachment details | Lines 140-153 |
| [`DelayedTaskDict`](../internal/database/models.py:155) | Delayed task information | Lines 155-163 |
| [`SpamMessageDict`](../internal/database/models.py:165) | Spam message details | Lines 165-174 |
| [`ChatSummarizationCacheDict`](../internal/database/models.py:176) | Cached summary information | Lines 176-188 |
| [`CacheDict`](../internal/database/models.py:190) | Generic cache entry | Lines 190-197 |
| [`CacheStorageDict`](../internal/database/models.py:199) | Cache storage entry | Lines 199-206 |

These TypedDict models provide:
- **Type safety**: IDE autocomplete and type checking
- **Documentation**: Clear field names and types
- **Validation**: Runtime validation via repository methods

---

## Repository Pattern

The database uses a repository pattern with 12 specialized repositories, each handling a specific domain:

| Repository | File | Purpose |
|---|---|---|
| `cache` | [`cache.py`](../internal/database/repositories/cache.py) | Unified cache operations |
| `chatInfo` | [`chat_info.py`](../internal/database/repositories/chat_info.py) | Chat metadata |
| `chatMessages` | [`chat_messages.py`](../internal/database/repositories/chat_messages.py) | Chat message operations |
| `chatSettings` | [`chat_settings.py`](../internal/database/repositories/chat_settings.py) | Per-chat configuration |
| `chatSummarization` | [`chat_summarization.py`](../internal/database/repositories/chat_summarization.py) | Chat summarization |
| `chatUsers` | [`chat_users.py`](../internal/database/repositories/chat_users.py) | User information and statistics |
| `common` | [`common.py`](../internal/database/repositories/common.py) | Common database operations |
| `delayedTasks` | [`delayed_tasks.py`](../internal/database/repositories/delayed_tasks.py) | Task scheduling |
| `divinations` | [`divinations.py`](../internal/database/repositories/divinations.py) | Tarot/runes readings and layout discovery |
| `mediaAttachments` | [`media_attachments.py`](../internal/database/repositories/media_attachments.py) | Media attachment management |
| `spam` | [`spam.py`](../internal/database/repositories/spam.py) | Spam detection and ham classification |
| `userData` | [`user_data.py`](../internal/database/repositories/user_data.py) | User key-value data |

### Accessing Repositories

All repositories are accessible through the main [`Database`](../internal/database/database.py:1) class:

```python
from internal.database import Database

db = Database(config)

# Access repositories
messages = db.chatMessages.getChatMessages(chatId=-1001234567890)
user = db.chatUsers.getChatUser(chatId=-1001234567890, userId=123456789)
settings = db.chatSettings.getChatSettings(chatId=-1001234567890)
```

### Repository Methods

Each repository provides methods for its domain. Common patterns include:

- **Query methods**: `get*`, `find*`, `list*` - Retrieve data
- **Create methods**: `add*`, `create*`, `save*` - Insert new records
- **Update methods**: `update*`, `set*` - Modify existing records
- **Delete methods**: `delete*`, `remove*` - Remove records

See individual repository files for complete method documentation.

---

## Best Practices

### 1. Always Use Context Managers

```python