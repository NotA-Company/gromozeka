
# Database Schema Documentation

This document provides comprehensive documentation for the Gromozeka bot's database schema, dood!

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
- [System Tables](#system-tables)
  - [settings](#settings)
- [Enums](#enums)
- [TypedDict Models](#typeddict-models)

---

## Overview

The Gromozeka bot uses SQLite as its database backend with a custom wrapper layer ([`DatabaseWrapper`](../internal/database/wrapper.py:128)) that provides:

- **Multi-source database support**: Route different chats to different database files
- **Thread-safe connection pooling**: Per-source thread-local connections
- **Migration system**: Version-controlled schema changes
- **Type-safe data access**: TypedDict models for all database entities
- **Automatic timestamp management**: Created/updated timestamps on all tables

The database stores chat messages, user information, settings, media attachments, spam detection data, and various caches to support the bot's functionality.

---

## Multi-Source Architecture

### Overview

The database wrapper supports routing different chats to different SQLite database files. This enables:

- **Data isolation**: Separate databases for different chat groups
- **Performance optimization**: Distribute load across multiple files
- **Backup flexibility**: Independent backup schedules per source
- **Read-only sources**: Support for read-only database replicas

### Configuration

Multi-source configuration is defined in the bot's config file:

```toml
[database]
default = "default"  # Default source name

[database.sources.default]
path = "data/bot.db"
readonly = false
pool-size = 5
timeout = 30

[database.sources.archive]
path = "data/archive.db"
readonly = true
pool-size = 3
timeout = 10

[database.chatMapping]
-1001234567890 = "archive"  # Route specific chat to archive source
```

### Routing Logic

The [`_getConnection()`](../internal/database/wrapper.py:223) method implements 3-tier routing:

1. **Tier 1 (Highest Priority)**: Explicit `dataSource` parameter
2. **Tier 2 (Medium Priority)**: Chat ID mapping lookup
3. **Tier 3 (Lowest Priority)**: Default source fallback

Example:
```python
# Explicit source routing (Tier 1)
db.getChatMessages(chatId=123, dataSource="archive")

# Chat mapping routing (Tier 2)
db.getChatMessages(chatId=-1001234567890)  # Routes to "archive" via mapping

# Default routing (Tier 3)
db.getChatMessages(chatId=456)  # Routes to "default" source
```

### Read-Only Sources

Sources marked as `readonly = true` will:
- Enable SQLite's `query_only` pragma
- Reject write operations with [`ValueError`](../internal/database/wrapper.py:290)
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
| 2 | [`migration_002_add_is_spammer_to_chat_users.py`](../internal/database/migrations/versions/migration_002_add_is_spammer_to_chat_users.py:1) | Adds `is_spammer` column to [`chat_users`](#chat_users) |
| 3 | [`migration_003_add_metadata_to_chat_users.py`](../internal/database/migrations/versions/migration_003_add_metadata_to_chat_users.py:1) | Adds `metadata` column to [`chat_users`](#chat_users) |
| 4 | [`migration_004_add_cache_storage_table.py`](../internal/database/migrations/versions/migration_004_add_cache_storage_table.py:1) | Creates [`cache_storage`](#cache_storage) table |
| 5 | [`migration_005_add_yandex_cache.py`](../internal/database/migrations/versions/migration_005_add_yandex_cache.py:1) | Adds Yandex Search cache table |
| 6 | [`migration_006_new_cache_tables.py`](../internal/database/migrations/versions/migration_006_new_cache_tables.py:1) | Adds Geocode Maps cache tables |
| 7 | [`migration_007_messages_metadata.py`](../internal/database/migrations/versions/migration_007_messages_metadata.py:1) | Adds `markup` and `metadata` columns to [`chat_messages`](#chat_messages) |

### Creating New Migrations

To create a new migration:

1. Create file: `internal/database/migrations/versions/migration_XXX_description.py`
2. Implement [`BaseMigration`](../internal/database/migrations/base.py:7) class with `version`, `description`, `up()`, and `down()` methods
3. Add `getMigration()` function returning the migration class
4. The migration will be auto-discovered on next startup

Example:
```python
from typing import Type
import sqlite3
from ..base import BaseMigration

class Migration008AddNewColumn(BaseMigration):
    version = 8
    description = "Add new_column to some_table"
    
    def up(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("""
            ALTER TABLE some_table
            ADD COLUMN new_column TEXT
        """)
    
    def down(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("""
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
| `markup` | TEXT | No | "" | JSON-serialized keyboard markup |
| `metadata` | TEXT | No | "" | JSON-serialized additional metadata |
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |

**Relationships**:
- References [`chat_users`](#chat_users) via `(chat_id, user_id)`
- References [`media_attachments`](#media_attachments) via `media_id`
- Self-references via `reply_id` and `root_message_id`

**TypedDict**: [`ChatMessageDict`](../internal/database/models.py:67)

**Example Query**:
```python
# Get recent messages from a chat
messages = db.getChatMessagesSince(
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
| `is_spammer` | BOOLEAN | No | FALSE | Whether user is marked as spammer |
| `metadata` | TEXT | No | "" | JSON-serialized additional metadata |
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | First seen timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last activity timestamp |

**Relationships**:
- Referenced by [`chat_messages`](#chat_messages) via `(chat_id, user_id)`
- Referenced by [`user_data`](#user_data) via `(chat_id, user_id)`

**TypedDict**: [`ChatUserDict`](../internal/database/models.py:104)

**Example Query**:
```python
# Get user info
user = db.getChatUser(chatId=-1001234567890, userId=123456789)
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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

**TypedDict**: [`ChatInfoDict`](../internal/database/models.py:118)

**Example Query**:
```python
# Get chat info
chat = db.getChatInfo(chatId=-1001234567890)
if chat and chat['is_forum']:
    topics = db.getChatTopics(chatId=chat['chat_id'])
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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

**Available Settings**: See [`ChatSettingsKey`](../internal/bot/models/chat_settings.py:41) enum for all available settings including:
- LLM model selection (`chat-model`, `summary-model`, etc.)
- Prompts (`chat-prompt`, `summary-prompt`, etc.)
- Feature flags (`use-tools`, `parse-images`, `detect-spam`, etc.)
- Spam detection thresholds
- Bayes filter configuration

**Example Query**:
```python
# Get chat settings
settings = db.getChatSettings(chatId=-1001234567890)
chatModel = settings.get('chat-model', 'default-model')

# Set a setting
db.setChatSetting(chatId=-1001234567890, key='parse-images', value='true')
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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

**Note**: Automatically updated when messages are saved via [`saveChatMessage()`](../internal/database/wrapper.py:853).

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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

**Note**: Automatically updated when messages are saved via [`saveChatMessage()`](../internal/database/wrapper.py:853).

---

## Media Tables

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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

**Example**: Store user preferences, facts mentioned in conversation, etc.

```python
# Store user data
db.addUserData(userId=123, chatId=-1001234567890, key='favorite_color', data='blue')

# Retrieve user data
userData = db.getUserData(userId=123, chatId=-1001234567890)
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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

**Indexes**:
- `chat_summarization_cache_ctfl_index` on `(chat_id, topic_id, first_message_id, last_message_id, prompt)`

**TypedDict**: [`ChatSummarizationCacheDict`](../internal/database/models.py:176)

**Cache Key Generation**: See [`_makeChatSummarizationCSID()`](../internal/database/wrapper.py:1996)

---

### cache_storage

Generic key-value cache storage with namespace support.

**Primary Key**: `(namespace, key)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `namespace` | TEXT | No | - | Cache namespace for organization |
| `key` | TEXT | No | - | Cache key |
| `value` | TEXT | No | - | Cached value (JSON-serialized) |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

**TypedDict**: [`CacheStorageDict`](../internal/database/models.py:199)

---

### Dynamic Cache Tables

The system automatically creates cache tables for each [`CacheType`](#cachetype):

- `cache_weather` - Weather API responses
- `cache_geocoding` - Geocoding API responses
- `cache_yandex_search` - Yandex Search API responses
- `cache_geocode_maps_search` - Geocode Maps search results
- `cache_geocode_maps_reverse` - Geocode Maps reverse geocoding
- `cache_geocode_maps_lookup` - Geocode Maps location lookups

**Schema** (all cache tables):

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `key` | TEXT | No | - | Cache key (PRIMARY KEY) |
| `data` | TEXT | No | - | Cached data (JSON-serialized) |
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

**TypedDict**: [`CacheDict`](../internal/database/models.py:190)

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
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

**TypedDict**: [`DelayedTaskDict`](../internal/database/models.py:155)

---

## System Tables

### settings

Stores global system settings and migration version tracking.

**Primary Key**: `key`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `key` | TEXT | No | - | Setting key |
| `value` | TEXT | Yes | NULL | Setting value |
| `created_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | No | CURRENT_TIMESTAMP | Last update timestamp |

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
- **Validation**: Runtime validation via [`_validateDictIs*`](../internal/database/wrapper.py:411) methods

---

## Best Practices

### 1. Always Use Context Managers

```python