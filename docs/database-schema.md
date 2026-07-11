
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
- [Webhook Tables](#webhook-tables)
  - [webhook_updates](#webhook_updates)
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
| 16 | [`migration_016_add_stat_tables.py`](../internal/database/migrations/versions/migration_016_add_stat_tables.py:1) | Creates [`stat_events`](#stat_events) and [`stat_aggregates`](#stat_aggregates) tables |
| 17 | [`migration_017_message_embeddings.py`](../internal/database/migrations/versions/migration_017_message_embeddings.py:1) | Creates [`message_embeddings`](#message_embeddings) table for semantic search |
| 18 | [`migration_018_message_embeddings_index.py`](../internal/database/migrations/versions/migration_018_message_embeddings_index.py:1) | Adds secondary index on `message_embeddings` (chat_id, model) |
| 19 | [`migration_019_add_webhook_updates_table.py`](../internal/database/migrations/versions/migration_019_add_webhook_updates_table.py:1) | Creates [`webhook_updates`](#webhook_updates) table for Max webhook ingestion |
| 20 | [`migration_020_user_memories.py`](../internal/database/migrations/versions/migration_020_user_memories.py:1) | Creates [`user_memories`](#user_memories) table (unified per-user memory store) with backfills from `user_data` + rolling-bio |
| 21 | [`migration_021_user_memories_soft_delete.py`](../internal/database/migrations/versions/migration_021_user_memories_soft_delete.py:1) | Adds nullable `deleted_at` to [`user_memories`](#user_memories) for soft-delete semantics (`down()` is a no-op — portable `DROP COLUMN` unavailable) |

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
| `message_type` | TEXT | No | 'text' | Type of message (see [`MessageType`](/internal/models/shared_enums.py)) |
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

**TypedDict**: [`ChatMessageDict`](../internal/database/models.py:108)

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
| `metadata` | TEXT | No | "" | JSON-serialized additional metadata (see note below) |
| `created_at` | TIMESTAMP | No | - | First seen timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last activity timestamp (must be provided explicitly) |

**Relationships**:
- Referenced by [`chat_messages`](#chat_messages) via `(chat_id, user_id)`

**`metadata` JSON convention:** the column holds a JSON object (`internal/bot/models/user_metadata.py` → `UserMetadataDict`, `total=False`) with boolean flags (`isSpammer`, `notSpammer`, `dropMessages`, `leftChat`) plus an optional `memoryRefinement` sub-dict keyed by `str(threadId)` (e.g. `"0"` for the main thread). Each `memoryRefinement[threadId]` entry (`UserMemoryThreadDict`) carries: `summary` (rolling short bio), `lastProcessedMessageId` + `lastProcessedMessageDate` (message cursor for `getChatMessagesSince`). The `lastRefinedTS` (unix timestamp of the last refinement run) is NO LONGER persisted here — it is tracked in-memory on `UserMemoriesHandler._lastRefinedTS` (lost on restart; absent → 0 → treated as due). Read via `CacheService.getUserMetadata()`; the nested `memoryRefinement` sub-dict must be written via read-modify-write through `CacheService.updateUserMetadata()` (full-dict replace, NO merge — see [`docs/llm/tasks.md`](llm/tasks.md) §3: `setUserMetadata(isUpdate=True)` shallow-merges at the top level and would wipe sibling threads). Single-row `(chatId, userId)` reads/writes are cached via `CacheService` (ADR-015; the cached `messages_count` is best-effort stale — incremented by raw SQL in `saveChatMessage`, bypassing the cache).

**TypedDict**: [`ChatUserDict`](../internal/database/models.py:163)

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

**TypedDict**: [`ChatInfoDict`](../internal/database/models.py:215)

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

**TypedDict**: [`ChatTopicInfoDict`](../internal/database/models.py:234)

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

### stat_events

Append-only event log for raw statistics events. Used by the statistics collection system to record events before aggregation.

**Primary Key**: `event_id` (app-generated UUID)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `event_id` | TEXT | No | - | App-generated UUID primary key |
| `event_type` | TEXT | No | - | Type of statistics event (e.g., 'llm_request', 'message_received') |
| `event_time` | TIMESTAMP | No | - | Timestamp when the event occurred |
| `data` | TEXT | No | - | JSON-encoded event payload (metric key -> value) |
| `labels` | TEXT | No | - | JSON-encoded dimension key-value pairs (e.g., consumer, model, provider) |
| `processed` | INTEGER | No | 0 | Boolean flag (0=unprocessed, 1=processed) |
| `processed_id` | TEXT | Yes | NULL | ID of the aggregate record that claimed this event |
| `claimed_at` | TIMESTAMP | Yes | NULL | Timestamp when event was claimed for processing |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp |

**Indexes:**
- `idx_stat_events_unprocessed` on `(processed, processed_id, claimed_at)` — for fast lookup of unprocessed/orphaned events
- `idx_stat_events_lookup` on `(event_type, event_time)` — for event lookup by type and time

**Note:** Created by `migration_016`. Part of the v3 statistics library (`lib/stats/`). See [`internal/database/stats_storage.py`](../internal/database/stats_storage.py) for `DatabaseStatsStorage` implementation.

---

### stat_aggregates

Pre-computed period buckets for aggregated statistics metrics. Produced by aggregating raw events from `stat_events`.

**Primary Key**: `(event_type, period_start, period_type, labels_hash, metric_key)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `event_type` | TEXT | No | - | Type of statistics event |
| `period_start` | TEXT | No | - | Start of the aggregation period (ISO-8601 formatted string) |
| `period_type` | TEXT | No | - | Period length ('hour', 'day', 'month', 'total') |
| `labels_hash` | TEXT | No | - | MD5 hex digest from labels |
| `labels` | TEXT | No | - | JSON-encoded dimension key-value pairs |
| `metric_key` | TEXT | No | - | Name of the metric (e.g., 'request_count', 'input_tokens') |
| `metric_value` | REAL | No | - | Numeric value of the metric (sum or count) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp |

**Period types:**
- `hour` — Hourly aggregation (period_start rounded to hour)
- `day` — Daily aggregation (period_start rounded to day)
- `month` — Monthly aggregation (period_start rounded to month)
- `total` — All-time aggregation (period_start = epoch)

**Labels include:**
- `consumer` — Consumer identifier (chat ID or `"__global__"` for rollup)
- `modelName` — LLM model name
- `modelId` — LLM model ID
- `provider` — LLM provider name
- `generationType` — Type of generation ('text', 'structured', 'image')

**Note:** Created by `migration_016`. Part of the v3 statistics library (`lib/stats/`). Automatically updated when `DatabaseStatsStorage.aggregate()` is called. See [`internal/database/stats_storage.py`](../internal/database/stats_storage.py) for implementation details.

---

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

**TypedDict**: [`MediaAttachmentDict`](../internal/database/models.py:255)

---

## User Data Tables (DROPPED)

### user_data

**Dropped in `migration_022`** (superseded by [`user_memories`](#user_memories)). Historical rows were backfilled into `user_memories` by `migration_020`.

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

**TypedDict**: [`SpamMessageDict`](../internal/database/models.py:303)

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

**TypedDict**: [`ChatSummarizationCacheDict`](../internal/database/models.py:326)

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

**TypedDict**: [`CacheStorageDict`](../internal/database/models.py:364)

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

**TypedDict**: [`CacheDict`](../internal/database/models.py:351)

**Available Namespaces**: See [`CacheType`](#cachetype) enum for all available cache namespaces including:
- `WEATHER` - Weather API responses
- `GEOCODING` - Geocoding API responses
- `YANDEX_SEARCH` - Yandex Search API responses
- `URL_CONTENT` - Cached URL content
- `URL_CONTENT_CONDENSED` - Cached condensed URL content
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

**TypedDict**: [`DelayedTaskDict`](../internal/database/models.py:284)

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

## Chat Search Tables

### message_embeddings

Stores one float32 embedding vector per `(chat_id, message_id)` to enable semantic ranking of chat-history search results. Produced by the `MessagePreprocessorHandler` (real-time, post-`saveChatMessage`) and the `ChatSearchHandler._dtCronJob` backfill `CRON_JOB` (catches up un-embedded rows; backfill runs whenever the per-chat `EMBEDDINGS_ENABLED` setting is on — there is no separate one-shot regen trigger); consumed by `ChatMessagesRepository.searchChatMessages` for cosine-similarity ranking. See [`docs/llm/database.md`](llm/database.md) §5.5 for repository usage, and [`docs/llm/configuration.md`](llm/configuration.md) for `[search-history]` config. There is no separate `BackfillWorker` class — backfill duty lives in `ChatSearchHandler`.

**Primary Key**: `(chat_id, message_id)`

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Chat identifier (matches `chat_messages.chat_id`) |
| `message_id` | TEXT | No | - | Message identifier (Telegram `int` → `MessageId.asStr()`; Max `str` verbatim) |
| `embedding` | BLOB | No | - | `array.array('f', vec).tobytes()` — raw little-endian float32 vector |
| `dimensions` | INTEGER | No | - | `len(embedding)`, derived in `saveMessageEmbedding` (not a separate arg) |
| `model` | TEXT | No | - | Name of the model that produced the vector (matches the resolved `EMBEDDING_MODEL` chat setting: per-chat → hard-coded `"local-embedding"`) |
| `created_at` | TIMESTAMP | No | - | Record creation timestamp (must be provided explicitly) |
| `updated_at` | TIMESTAMP | No | - | Last update timestamp (must be provided explicitly) |

**Indexes**:
- `idx_message_embeddings_chat_model` on `(chat_id, model)` — speeds up `_loadEmbeddingsFromDb` (filters by both chat and model name). Created by `migration_018`.
- The composite PK covers per-chat enumeration (`WHERE chat_id = ?`) via its leftmost prefix.

**Cross-RDBMS portability:**
- `BLOB` type is portable across SQLite, PostgreSQL (`BYTEA`), and MySQL (`BLOB`).
- `dimensions` is stored per row so a chat that switches `EMBEDDING_MODEL` can detect stale rows without joining the LLM registry at SQL time.
- No `AUTOINCREMENT` / `SERIAL` — composite natural key follows the project convention (see [`docs/sql-portability-guide.md`](sql-portability-guide.md)).
- `created_at` / `updated_at` are set by application code (no DB default — matches `migration_013` rules).

**Note**: Created by `migration_017`. Only populated when `[search-history] enabled = true`. The embedding dispatch in `MessagePreprocessorHandler.newMessageHandler` calls `db.chatEmbeddings.saveMessageEmbedding` for messages saved in chats with `EMBEDDINGS_ENABLED = true` (the dispatch runs whenever both `[search-history].enabled` and `EMBEDDINGS_ENABLED` are on — `_searchEnabled` is cached at construction time); the `ChatSearchHandler._dtCronJob` `CRON_JOB` handler closes the gap for messages that were saved before the feature was turned on or for chats that enabled the feature with no prior embeddings (round-robin, one chat per tick, batch `BACKFILL_DEFAULT_BATCH_SIZE` messages). There is no separate `BackfillWorker` class — backfill duty lives in `ChatSearchHandler`.

---

### vec_message_embeddings_N (virtual table)

Ephemeral `vec0` virtual tables (one per embedding dimension in use, e.g. `vec_message_embeddings_384`, `vec_message_embeddings_1024`) that mirror `message_embeddings` rows for native cosine-similarity KNN search via the `sqlite-vec` extension. Created lazily at runtime by `SQLite3Provider.createVectorTable()` on the first write of a given dimension (in `ChatEmbeddingsRepository.saveMessageEmbedding`); no migration creates them. **Authoritative data lives in [`message_embeddings`](#message_embeddings)** — vec0 tables are rebuildable sidecar indexes and carry nothing the app cannot reconstruct.

Not present when `sqlite-vec` is not installed; the numpy search path is used instead.

```sql
CREATE VIRTUAL TABLE vec_message_embeddings_384 USING vec0(
    message_id TEXT,
    chat_id INTEGER PARTITION KEY,
    model TEXT PARTITION KEY,
    date TEXT,                            -- ISO-8601 from chat_messages; enables maxMessages pre-filter
    embedding FLOAT[384] distance_metric=cosine
);
```

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `message_id` | TEXT | No | Message identifier (matches `message_embeddings.message_id`) |
| `chat_id` | INTEGER | No | Chat identifier; `PARTITION KEY` — `WHERE chat_id = ?` prunes the search |
| `model` | TEXT | No | Embedding model name; `PARTITION KEY` — `WHERE model = ?` prunes the search |
| `date` | TEXT | No | ISO-8601 timestamp from `chat_messages.date`; enables `maxMessages` pre-filter via `date >= :minDate` |
| `embedding` | FLOAT[N] | No | float32 vector, `N` = embedding dimension (matches table-name suffix). `distance_metric=cosine` |

**Lifecycle:** written by `saveMessageEmbedding()` (dual-write: `message_embeddings` + vec0). Stale rows from a previous embedding model are cleaned up statelessly by `ChatSearchHandler._dtCronJob`, which lists all `vec_message_embeddings_%` tables via `listTables()` and runs `DELETE FROM {table} WHERE chat_id = :chatId AND model != :currentModel` on each. No `AUTOINCREMENT`, no `DEFAULT CURRENT_TIMESTAMP` — vec0 is not a standard table and the standard portability rules do not apply to its DDL.

---

## Webhook Tables

### webhook_updates

Stores raw incoming Max Messenger webhook payloads awaiting consumption by the bot. Written by the standalone webhook receiver process (`internal/max_webhook_receiver/`) on every webhook POST; the bot's normal long-poll loop reads and marks rows processed. See [`docs/llm/architecture.md`](llm/architecture.md) for the two-process webhook model.

**Primary Key**: `id` (application-generated UUID)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | TEXT | No | - | Application-generated UUID identifying the update (no `AUTOINCREMENT`) |
| `received_at` | TIMESTAMP | No | - | When the webhook payload was received and stored (set by application code) |
| `update_type` | TEXT | No | - | Coarse `update_type` tag extracted from the Max payload, used for routing |
| `raw_json` | TEXT | No | - | Full webhook request body serialized as a JSON string |
| `processed` | INTEGER | No | 0 | Whether the update has been consumed (0 = pending, 1 = processed) |
| `processed_at` | TIMESTAMP | Yes | NULL | When the update was marked processed, or NULL if still pending |

**Indexes**:
- `idx_webhook_updates_unprocessed` on `(processed, received_at)` — backs the unprocessed-updates query (`WHERE processed = 0 ORDER BY received_at ASC`)

**TypedDict**: [`WebhookUpdatesRow`](../internal/database/models.py:303)

**Note**: Created by `migration_019`. No `AUTOINCREMENT`/`SERIAL` and no `DEFAULT CURRENT_TIMESTAMP` — `id` is a caller-generated UUID and both timestamps are set by application code, mirroring the repo-wide portability rules. Processed rows are reaped by the receiver's background cleanup task (default TTL 1 hour). The bot only writes to this table when webhook mode is on; the receiver process always writes here regardless of the bot's `enabled` flag.

---

## User Memory Tables

### user_memories

Unified per-(chat, user, thread) memory store — durable facts, preferences, events, relationships, and high-level bio notes about a user. Retires the legacy `user_data` key-value table (dropped in `migration_022`) and the rolling-bio JSON blob (`chat_users.metadata.memoryRefinement`); both were backfilled into this table by `migration_020`. See [`docs/llm/memories/user-memories.md`](llm/memories/user-memories.md) (canonical durable summary) and [`docs/plans/user-memories-v1.md`](plans/user-memories-v1.md).

Semantic search runs over a vec0 virtual table (`vec_user_memories_{dim}`, cosine distance) that is **not** created by the migration — it is created lazily at runtime on first write (mirrors `message_embeddings` / `vec_message_embeddings_{dim}`). Unlike chat-history search there is no BLOB side table: `embedding_model` / `embedding_dimensions` are tracked on `user_memories` itself and vec0 is the sole embedding store. When vec0 is unavailable, `searchMemories` returns `[]` (no numpy fallback).

**Primary Key**: `(chat_id, user_id, memory_id)` — composite natural key (no `AUTOINCREMENT`).

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `chat_id` | INTEGER | No | - | Chat identifier |
| `user_id` | INTEGER | No | - | User the memory is about |
| `thread_id` | INTEGER | Yes | NULL | Thread scope; NULL = cross-thread permanent within the chat |
| `memory_id` | TEXT | No | - | App-generated UUID hex, unique within (chat_id, user_id) |
| `type` | TEXT | No | - | `MemoryType` value: bio\|preference\|fact\|event\|relationship |
| `content` | TEXT | No | - | Free-text memory body (source of truth for re-embedding) |
| `tags` | TEXT | No | `'[]'` | JSON array of freeform tag strings |
| `permanent` | INTEGER | No | 0 | Boolean 0/1 — permanent memories are always injected |
| `source` | TEXT | No | `'refinement'` | Provenance: refinement\|chat\|migration\|user |
| `embedding_model` | TEXT | Yes | NULL | Model that produced the vec0 embedding (NULL = not yet embedded) |
| `embedding_dimensions` | INTEGER | Yes | NULL | Embedding dimension count (NULL = not yet embedded) |
| `created_at` | TIMESTAMP | No | - | Creation timestamp (application-set) |
| `updated_at` | TIMESTAMP | No | - | Last-update timestamp (application-set) |
| `deleted_at` | TIMESTAMP | Yes | NULL | Soft-delete timestamp (`migration_021`); `NULL` = live. Set application-side in `deleteMemory` via `dbUtils.getCurrentTimestamp()` (no DB default). Live reads filter `AND deleted_at IS NULL`; `getMemoriesByIds` is the one read that skips the filter (historical reconstruction). |

**Indexes**:
- `idx_user_memories_chat_user_thread` on `(chat_id, user_id, thread_id, updated_at DESC)` — backs `getLatestMemories` and same-thread retrieval.
- `idx_user_memories_chat_user_permanent` on `(chat_id, user_id, permanent, updated_at DESC)` — backs `getPermanentMemories`.
- `idx_user_memories_type` on `(chat_id, user_id, type)` — backs type-filtered scans.

**TypedDict**: [`UserMemoryDict`](../internal/database/models.py:551) (snake_case keys; `score: NotRequired[float]` populated by semantic search).

**Enum**: [`MemoryType`](../internal/database/models.py:473) (`BIO`/`PREFERENCE`/`FACT`/`EVENT`/`RELATIONSHIP`); [`UserMemorySource`](../internal/database/models.py:515) (`REFINEMENT`/`CHAT`/`MIGRATION`/`USER`).

**Repository** (`UserMemoriesRepository`, accessed as `db.userMemories`) — 10 public methods; all SQL goes through `BaseSQLProvider`:
- `addMemory(chatId, userId, memoryId, *, type, content, tags, permanent, source, embedding=None, embeddingModel=None, threadId=None) -> None` — INSERT (caller generates the UUID). `source` is a `UserMemorySource`; `threadId` is keyword-only; when both `embedding` (`List[float]`) and `embeddingModel` are provided the row is embedded during add.
- `deleteMemory(chatId, userId, memoryId) -> bool` — SOFT DELETE: sets `deleted_at` + bumps `updated_at`, drops the vec0 row, nulls `embedding_model`/`embedding_dimensions` (via `deleteMemoryEmbedding(..., vecOnly=False)`). Unrestricted (may target permanent). The row survives so `getMemoriesByIds` can still resolve it; never raises (returns `False` on error or already-deleted).
- `getPermanentMemories(chatId, userId, threadId, *, limit=10) -> List[UserMemoryDict]` — merges cross-thread permanent (`thread_id IS NULL`) AND this-thread permanent (`thread_id = :threadId`); bio is thread-scoped so a thread's permanent block includes its own bio. Filters `deleted_at IS NULL`.
- `getLatestMemories(chatId, userId, threadId, *, limit=5) -> List[UserMemoryDict]` — thread-scoped newest-first, **ephemeral-only** (`permanent = 0`); permanent memories are served by `getPermanentMemories`. Filters `deleted_at IS NULL`.
- `getMemoriesByIds(memoryIds: List[str], *, chatId: Optional[int] = None, dataSource: Optional[str] = None) -> List[UserMemoryDict]` — the single read that does NOT filter `deleted_at`: resolves UUIDs to content for historical message reconstruction (compact-ID storage — see [`docs/llm/memories/user-memories.md`](llm/memories/user-memories.md) "By-id resolution cache"). No `chatId`/`userId` scoping in the WHERE clause (UUIDs globally unique); `chatId`/`dataSource` are routing-only (forwarded to `getProvider(..., readonly=True)`); default `None` → default DB.
- `searchMemories(chatId, userId, queryEmbedding=None, *, threadId=None, type=None, tags=None, permanent=None, limit=20, embeddingModel, offset=0) -> List[UserMemoryDict]` — filter-only (`queryEmbedding is None`, plain SQL scan, `score = 0.0`) or semantic (vec0 KNN, `score = 1.0 - distance`). `queryEmbedding` is `Optional[List[float]]`; `embeddingModel` (required, pass `None` for filter-only) replaces the old `dimensions` arg and is part of the vec0 `model` partition filter. Always scoped to one `(chat_id, user_id)`; `tags` applied as a portable SQL `LIKE '%"tagN"%'` filter (ANY-match) against the JSON-TEXT `tags` column. Both modes filter `deleted_at IS NULL`.
- `saveMemoryEmbedding(chatId, userId, memoryId, embedding, embeddingModel) -> bool` — lazy-create `vec_user_memories_{dim}` + upsert the vector (`embedding` is `List[float]`, `embeddingModel` the model name) + set `embedding_model`/`embedding_dimensions` (vec0 write must succeed before provenance is set). Its internal row SELECT also filters `deleted_at IS NULL` (defense-in-depth — a deleted memory is never re-embedded).
- `deleteMemoryEmbedding(chatId, userId, memoryId) -> None` — best-effort vec0 DELETE across every `vec_user_memories_{N}` table; never raises.
- `getMemoriesWithoutEmbeddings(chatId, *, limit=50, modelName=None, dimensions=None, dataSource=None) -> List[UserMemoryDict]` — single-table stale detection (NULL `embedding_model`/`embedding_dimensions`, or either differing from the active value); backs the regen cron and the initial backfill.
- `deleteObsoleteMemoryEmbeddings(chatId, currentModel, currentDimensions) -> int` — model-drift cleanup: resets stale rows' provenance to NULL and drops their vec0 rows.

**Backfills** (`migration_020.up()`):
- `user_data` rows → permanent cross-thread `type='fact'`, `content="{key}: {data}"`, `tags=[]`, `source='migration'`, original timestamps preserved.
- `chat_users.metadata.memoryRefinement[str(threadId)]` entries with a non-empty summary → permanent thread-scoped `type='bio'`, `tags=["migrated_bio"]`, `source='migration'`, summary preserved in `content`.

**Note**: Created by `migration_020`; `deleted_at` added by `migration_021` (soft-delete — `down()` is a no-op that logs, since a portable `DROP COLUMN` is unavailable and a nullable additive column is safe on rollback). No `AUTOINCREMENT`/`SERIAL`, no `DEFAULT CURRENT_TIMESTAMP` — `memory_id` is an app-generated UUID and timestamps are application-set. `down()` for migration 020 drops only `user_memories`; the legacy `user_data` table was subsequently dropped by `migration_022` (superseded by `user_memories`), and `chat_users.metadata` is left untouched (the refinement rewrite stopped writing the rolling-bio blob, and the `userSummary` reader/field was removed entirely in Phase 4b — stale blobs are simply never read). The vec0 runtime table (`vec_user_memories_{dim}`) is NOT created by a migration — it is created lazily on first write at runtime.

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

**Defined in**: [`internal/database/models.py:28`](../internal/database/models.py:28)

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
| `DELETED` | Message deleted |
| `USER_CONFIG_ANSWER` | Answer to some config option |

---

### MediaStatus

Tracks media processing status.

**Defined in**: [`internal/database/models.py:15`](../internal/database/models.py:15)

| Value | Description |
|-------|-------------|
| `NEW` | Newly received, not yet processed |
| `PENDING` | Processing in progress |
| `DONE` | Processing completed successfully |
| `FAILED` | Processing failed |

---

### SpamReason

Indicates why a message was marked as spam.

**Defined in**: [`internal/database/models.py:95`](../internal/database/models.py:95)

| Value | Description |
|-------|-------------|
| `AUTO` | Automatically detected as spam |
| `USER` | Marked as spam by regular user |
| `ADMIN` | Marked as spam by admin |
| `UNBAN` | User unbanned (spam marking removed) |

---

### CacheType

Defines available cache types for dynamic cache tables.

**Defined in**: [`internal/database/models.py:377`](../internal/database/models.py:377)

| Value | Description |
|-------|-------------|
| `WEATHER` | Weather API cache |
| `GEOCODING` | Geocoding API cache |
| `YANDEX_SEARCH` | Yandex Search API cache |
| `URL_CONTENT` | Cached content of URL |
| `URL_CONTENT_CONDENSED` | Cached condensed content of URL |
| `GM_SEARCH` | Geocode Maps search cache |
| `GM_REVERSE` | Geocode Maps reverse geocoding cache |
| `GM_LOOKUP` | Geocode Maps lookup cache |

---

## TypedDict Models

All database queries return strongly-typed dictionaries defined in [`internal/database/models.py`](../internal/database/models.py:1):

| TypedDict | Description | Definition |
|-----------|-------------|------------|
| [`ChatMessageDict`](../internal/database/models.py:108) | Chat message with user and media info | Lines 108-160 |
| [`ChatUserDict`](../internal/database/models.py:163) | Chat user information | Lines 163-186 |
| [`ChatInfoDict`](../internal/database/models.py:215) | Chat metadata | Lines 215-231 |
| [`ChatTopicInfoDict`](../internal/database/models.py:234) | Forum topic information | Lines 234-252 |
| [`MediaAttachmentDict`](../internal/database/models.py:255) | Media attachment details | Lines 255-281 |
| [`DelayedTaskDict`](../internal/database/models.py:284) | Delayed task information | Lines 284-300 |
| [`SpamMessageDict`](../internal/database/models.py:303) | Spam message details | Lines 303-323 |
| [`WebhookUpdatesRow`](../internal/database/models.py:303) | Max webhook payload awaiting consumption | - |
| [`ChatSummarizationCacheDict`](../internal/database/models.py:326) | Cached summary information | Lines 326-348 |
| [`CacheDict`](../internal/database/models.py:351) | Generic cache entry | Lines 351-361 |
| [`CacheStorageDict`](../internal/database/models.py:364) | Cache storage entry | Lines 364-374 |

These TypedDict models provide:
- **Type safety**: IDE autocomplete and type checking
- **Documentation**: Clear field names and types
- **Validation**: Runtime validation via repository methods

---

## Repository Pattern

The database uses a repository pattern with 15 specialized repositories, each handling a specific domain:

| Repository | File | Purpose |
|---|---|---|
| `cache` | [`cache.py`](../internal/database/repositories/cache.py) | Unified cache operations |
| `chatEmbeddings` | [`chat_embeddings.py`](../internal/database/repositories/chat_embeddings.py) | Chat message embeddings for semantic search |
| `chatInfo` | [`chat_info.py`](../internal/database/repositories/chat_info.py) | Chat metadata |
| `chatMessages` | [`chat_messages.py`](../internal/database/repositories/chat_messages.py) | Chat message operations |
| `chatSearch` | [`chat_search.py`](../internal/database/repositories/chat_search.py) | Chat history search with semantic ranking |
| `chatSettings` | [`chat_settings.py`](../internal/database/repositories/chat_settings.py) | Per-chat configuration |
| `chatSummarization` | [`chat_summarization.py`](../internal/database/repositories/chat_summarization.py) | Chat summarization |
| `chatUsers` | [`chat_users.py`](../internal/database/repositories/chat_users.py) | User information and statistics |
| `common` | [`common.py`](../internal/database/repositories/common.py) | Common database operations |
| `delayedTasks` | [`delayed_tasks.py`](../internal/database/repositories/delayed_tasks.py) | Task scheduling |
| `divinations` | [`divinations.py`](../internal/database/repositories/divinations.py) | Tarot/runes readings and layout discovery |
| `mediaAttachments` | [`media_attachments.py`](../internal/database/repositories/media_attachments.py) | Media attachment management |
| `spam` | [`spam.py`](../internal/database/repositories/spam.py) | Spam detection and ham classification |
| `userMemories` | [`user_memories.py`](../internal/database/repositories/user_memories.py) | Unified per-(chat, user, thread) structured memory store (`migration_020`; vec0-backed semantic search) |
| `webhookUpdates` | [`webhook_updates.py`](../internal/database/repositories/webhook_updates.py) | Max webhook payload storage and consumption |

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