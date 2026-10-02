---
category: reference
description: "Reference index for the database layer: schema, repositories, migrations, and SQL portability."
---

# Database Documentation

Welcome to the Gromozeka bot's database documentation. This directory contains comprehensive documentation for the database schema and operations.

> **Canonical sources.** This file is a landing-page overview; for authoritative
> schema details, see [`database-schema.md`](database-schema.md) (human-facing)
> and [`database-schema-llm.md`](database-schema-llm.md) (LLM-facing). Counts
> and method signatures are not duplicated here; when in doubt against code,
> the schema docs are authoritative.


## Documentation Files

### [Database Schema Documentation](database-schema.md)
**Audience**: Developers, Database Administrators, System Architects

The complete technical reference for the database schema, including:
- Detailed table structures with all columns and constraints
- Multi-source architecture and routing configuration
- Migration system and version control
- Relationships and foreign keys
- Enums and TypedDict models
- Best practices and usage examples

**Use this when you need to**:
- Understand the complete database structure
- Learn about multi-source routing and configuration
- Create or modify database migrations
- Understand table relationships and constraints
- Reference TypedDict models for type-safe operations

### [Database Schema Reference for LLMs](database-schema-llm.md)
**Audience**: AI Assistants, Code Generation Tools, LLM-based Development

A streamlined reference optimized for LLM consumption, featuring:
- Concise table definitions with SQL CREATE statements
- Quick-reference API method signatures
- Common query patterns and examples
- Enum value listings
- Essential operation examples

**Use this when you need to**:
- Generate database-related code
- Quickly look up method signatures
- Find common query patterns
- Reference enum values
- Get concise table structure information

## Quick Navigation

### Core Concepts

- **Multi-Source Architecture**: [Schema Doc §Multi-Source Architecture](database-schema.md#multi-source-architecture)
- **Migration System**: [Schema Doc §Migration System](database-schema.md#migration-system)
- **TypedDict Models**: [Schema Doc §TypedDict Models](database-schema.md#typeddict-models)

### Table Categories

#### Core Tables
- [`chat_messages`](database-schema.md#chat_messages) - All chat messages with metadata
- [`chat_users`](database-schema.md#chat_users) - Per-chat user information
- [`chat_info`](database-schema.md#chat_info) - Chat metadata and configuration
- [`chat_topics`](database-schema.md#chat_topics) - Forum topic information
- [`chat_settings`](database-schema.md#chat_settings) - Per-chat configuration

#### Statistics Tables
- [`stat_events`](database-schema.md#stat_events) - Raw stat events
- [`stat_aggregates`](database-schema.md#stat_aggregates) - Aggregated statistics

#### Media Tables
- [`media_groups`](database-schema.md#media_groups) - Media group metadata
- [`media_attachments`](database-schema.md#media_attachments) - Media file information

#### User Memory Tables
- [`user_memories`](database-schema.md#user_memories) - Unified per-(chat, user, thread) structured memory store (permanent + ephemeral, vec0-backed semantic search)

#### Spam Detection Tables
- [`spam_messages`](database-schema.md#spam_messages) - Spam message tracking
- [`ham_messages`](database-schema.md#ham_messages) - Legitimate message tracking
- [`bayes_tokens`](database-schema.md#bayes_tokens) - Bayesian filter token statistics
- [`bayes_classes`](database-schema.md#bayes_classes) - Bayesian filter class statistics

#### Divination Tables
- [`divinations`](database-schema.md#divinations) - Tarot/runes divination readings
- [`divination_layouts`](database-schema.md#divination_layouts) - Cached divination layout definitions

#### Chat Search Tables
- [`models`](database-schema.md#models) - Embedding-model provenance registry (model name + dimensions → `model_id`); backing store for `chat_messages.model_id`, `user_memories.model_id`, and both vec0 families
- [`vec_message_embeddings_N`](database-schema.md#vec_message_embeddings_n-virtual-table) - vec0 virtual tables (one per embedding dimension; partition key = `model_id`)

#### Webhook Tables
- `webhook_updates` - moved to the webhook receiver's own database (ADR-025); dropped from the bot's schema by `migration_029`

#### Cache Tables
- [`chat_summarization_cache`](database-schema.md#chat_summarization_cache) - Cached summaries
- [`cache_storage`](database-schema.md#cache_storage) - Generic key-value cache
- [`cache`](database-schema.md#cache) - Per-type cache entries

#### Task Management Tables
- [`delayed_tasks`](database-schema.md#delayed_tasks) - Scheduled task execution

#### System Tables
- [`settings`](database-schema.md#settings) - Global system settings

### Common Operations

#### Message Operations
- [Save Message](database-schema-llm.md#message-operations) - Store new messages
- [Get Messages Since Date](database-schema-llm.md#message-operations) - Retrieve recent messages
- [Get Message by ID](database-schema-llm.md#message-operations) - Fetch specific message
- [Get Messages by Root ID](database-schema-llm.md#message-operations) - Get conversation threads

#### User Operations
- [Save/Update User](database-schema-llm.md#user-operations) - Store user information
- [Get User](database-schema-llm.md#user-operations) - Retrieve user data
- [Mark User as Spammer](database-schema-llm.md#user-operations) - Spam management

#### Chat Operations
- [Save/Update Chat Info](database-schema-llm.md#chat-operations) - Store chat metadata
- [Get Chat Info](database-schema-llm.md#chat-operations) - Retrieve chat information
- [Save Topic](database-schema-llm.md#chat-operations) - Store forum topics

#### Settings Operations
- [Get Chat Setting](database-schema-llm.md#settings-operations) - Retrieve configuration
- [Set Chat Setting](database-schema-llm.md#settings-operations) - Update configuration

#### Cache Operations
- [Get Cache](database-schema-llm.md#cache-operations) - Retrieve cached data
- [Set Cache](database-schema-llm.md#cache-operations) - Store cached data

## Key Features

### SQL Portability Overview
The database system is designed for cross-RDBMS compatibility, supporting multiple database backends:
- **Registered providers**: SQLite (`sqlite3`) and SQLink (`sqlink`) — the only two wired into the `getSqlProvider` factory today (see [`lib/db/providers/__init__.py`](../lib/db/providers/__init__.py:90))
- **Implemented, not yet selectable**: MySQL and PostgreSQL provider classes exist at [`lib/db/providers/mysql.py`](../lib/db/providers/mysql.py) and [`lib/db/providers/postgresql.py`](../lib/db/providers/postgresql.py) but are not registered in the factory. SQL must still stay portable so they can be turned on without rewrites.
- **Provider abstraction**: Common interface through `BaseSQLProvider` class
- **Portable operations**: Provider-specific methods handle SQL dialect differences
- **Type safety**: Consistent TypedDict models across all providers

Learn more: [SQL Portability Guide](sql-portability-guide.md)

### Multi-Source Database Support
The database system supports routing different chats to different database files:
- **Data isolation**: Separate databases for different chat groups
- **Performance optimization**: Distribute load across multiple files
- **Read-only sources**: Support for read-only database replicas
- **3-tier routing**: Explicit source, chat mapping, or default fallback
- **Repository pattern**: Organized access through specialized repositories
- **Cross-provider support**: Use different database types for different sources

Learn more: [Multi-Source Architecture](database-schema.md#multi-source-architecture)

### Version-Controlled Migrations
Automatic schema versioning and migration system:
- **Auto-discovery**: Migrations loaded from versions directory
- **Sequential execution**: Migrations run in order by version
- **Rollback support**: Each migration has up() and down() methods
- **Per-source execution**: Independent migration for each database

Learn more: [Migration System](database-schema.md#migration-system)

### Type-Safe Data Access
All database operations use TypedDict models:
- **Type safety**: IDE autocomplete and type checking
- **Documentation**: Clear field names and types
- **Validation**: Runtime validation for data integrity
- **Repository pattern**: Organized access through 15 specialized repositories

Learn more: [TypedDict Models](database-schema.md#typeddict-models)

## SQL Portability

### Overview

The Gromozeka database system is designed to work with multiple relational database management systems (RDBMS) through a provider abstraction layer. This allows you to choose the database that best fits your needs and switch between them with minimal code changes.

### Supported Database Providers

- **SQLite** (`sqlite3`, default) — registered in the `getSqlProvider` factory; embedded file-based database with optional `sqlite-vec` vector search ([`SQLite3Provider`](../lib/db/providers/sqlite3.py:1), `aiosqlite`)
- **SQLink** (`sqlink`) — registered in the factory; async HTTP client for a remote SQLink database server, with optional proxy support ([`SQLinkProvider`](../lib/db/providers/sqlink.py:1))
- **MySQL** (`mysql`) — implemented ([`MySQLProvider`](../lib/db/providers/mysql.py:1), `aiomysql`) but **not yet registered** in the factory; cannot be selected via config today
- **PostgreSQL** (`postgresql`) — implemented ([`PostgreSQLProvider`](../lib/db/providers/postgresql.py:1), `asyncpg`) but **not yet registered** in the factory; cannot be selected via config today

### Ownership of Portability Details

The [SQL Portability Guide](sql-portability-guide.md) owns the provider hook contracts (`upsert()` with the `ExcludedValue` marker, `applyPagination()`, `getCaseInsensitiveComparison()` / `getLikeComparison()`, `getTextType()`), per-provider considerations, the no-`DEFAULT CURRENT_TIMESTAMP` timestamp rule, and portability best practices — always use those hooks instead of hand-writing dialect-specific SQL. Multi-source provider configuration (TOML `[database.providers.<name>]` with a `provider` field and a `parameters` sub-table of constructor kwargs) is owned by the [Multi-Source Database Configuration Guide](database-multi-source.md).

### Repository Pattern Architecture

The database system uses a repository pattern: each repository is exposed as an attribute on the `Database` wrapper (for example `db.chatMessages`) and owns one domain of data operations, with all SQL going through `BaseSQLProvider`. The one exception is the webhook receiver's `WebhookUpdatesRepository` — since ADR-025 it lives in [`lib/max_webhook_receiver/`](../lib/max_webhook_receiver/repository.py) over the receiver's own database and is not on the bot's `Database` wrapper.

- **Full method signatures (owner)**: [Database Operations](database-schema-llm.md#database-operations) in `database-schema-llm.md`
- **Human-readable repository index (owner)**: [Repository Pattern](database-schema.md#repository-pattern) in `database-schema.md`
- **Repository sources**: [`internal/database/repositories/`](../internal/database/repositories/)

## Getting Started

### For Developers

1. **Read the Schema Documentation**: Start with [`database-schema.md`](database-schema.md) to understand the complete database structure
2. **Review the Database Class**: Check [`Database`](../internal/database/database.py:1) for the main database interface
3. **Explore Repository Classes**: See [`internal/database/repositories/`](../internal/database/repositories/) for specialized data access methods
4. **Explore TypedDict Models**: See [`internal/database/models.py`](../internal/database/models.py:1) for data structures
5. **Study Migration Examples**: Look at [`internal/database/migrations/versions/`](../internal/database/migrations/versions/) for migration patterns

### For LLM-Based Development

1. **Use the LLM Reference**: Start with [`database-schema-llm.md`](database-schema-llm.md) for quick lookups
2. **Reference Common Patterns**: Check [Common Query Patterns](database-schema-llm.md#common-query-patterns) section
3. **Copy Method Signatures**: Use the [Database Operations](database-schema-llm.md#database-operations) section for exact signatures
4. **Check Enum Values**: Reference [Enums](database-schema-llm.md#enums) section for valid values

## Usage Examples

### Basic Message Storage
```python
from datetime import datetime
from internal.database.models import MessageCategory, MessageType

# Save a message using repository pattern
await db.chatMessages.saveChatMessage(
    date=datetime.now(),
    chatId=-1001234567890,
    userId=123456789,
    messageId="12345",
    messageText="Hello, world!",
    messageType=MessageType.TEXT,
    messageCategory=MessageCategory.USER
)

# Retrieve recent messages
messages = await db.chatMessages.getChatMessagesSince(
    chatId=-1001234567890,
    sinceDateTime=datetime.now() - timedelta(hours=1),
    limit=50
)

# Get a specific message by ID
message = await db.chatMessages.getChatMessageByMessageId(
    chatId=-1001234567890,
    messageId="12345"
)
```

### Multi-Source Routing

Reads route through a 3-tier chain (explicit `dataSource` parameter, then chat mapping, then the default source); per-chat writes route by `chatId`. Worked routing examples and the operator-level configuration behind them are owned by the [Multi-Source Database Configuration Guide](database-multi-source.md#routing-priority).

### Chat Settings Management
```python
# Get all settings for a chat
settings = await db.chatSettings.getChatSettings(chatId=-1001234567890)
# Returns Dict[str, tuple[str, int]] where tuple is (value, updated_by)
model = settings.get('chat-model', ('gpt-4', 0))[0]  # Index [0] for value

# Set a specific setting
await db.chatSettings.setChatSetting(
    chatId=-1001234567890,
    key='parse-images',
    value='true',
    updatedBy=userId  # REQUIRED keyword-only argument
)

# Get a specific setting value
settingValue = await db.chatSettings.getChatSetting(
    chatId=-1001234567890,
    setting='parse-images'
)
```

### Cache Operations Examples
```python
from lib.cache import GenericDatabaseCache
from internal.database.models import CacheType

cache = GenericDatabaseCache(
    manager=db.manager,
    namespace=CacheType.WEATHER,
)

# Set cache value
await cache.set(
    key='weather-123',
    value={"temp": 20},
)

# Get cache value (TTL-aware)
cachedData = await cache.get(
    key='weather-123',
    ttl=3600
)
```

### SQL Portability Examples

Provider-method usage (pagination, case-insensitive comparison, portable upsert with `ExcludedValue`) and per-provider TOML configuration examples are owned by the [SQL Portability Guide](sql-portability-guide.md); multi-source configuration examples live in the [Multi-Source Database Configuration Guide](database-multi-source.md).

## Related Documentation

- **Database Class**: [`internal/database/database.py`](../internal/database/database.py:1)
- **Database Manager**: [`lib/db/manager.py`](../lib/db/manager.py:1)
- **Repository Base Class**: [`internal/database/repositories/base.py`](../internal/database/repositories/base.py:1)
- **Database Models**: [`internal/database/models.py`](../internal/database/models.py:1)
- **Migration Manager**: [`internal/database/migrations/manager.py`](../internal/database/migrations/manager.py:59)
- **Migration Base Class**: [`internal/database/migrations/base.py`](../internal/database/migrations/base.py:41)
- **Chat Settings Keys**: [`internal/bot/models/chat_settings.py`](../internal/bot/models/chat_settings.py:281)

## Development Guidelines

### Creating New Migrations

1. Create `internal/database/migrations/versions/migration_XXX_description.py` with the next sequential version number
2. Implement a `BaseMigration` subclass (`version`, `description`, `up()`, `down()`) plus a `getMigration()` function
3. The migration is auto-discovered on next startup

The full recipe — worked example, portable-SQL requirements, and primary-key strategies — is owned by [Adding a Database Migration](llm/database.md#4-adding-a-database-migration) in the agent guide.

### Best Practices

1. **Always use context managers** for database operations
2. **Specify chatId** for operations that support multi-source routing
3. **Use TypedDict types** for type-safe returns
4. **Check return values** - most operations return `bool` for success/failure
5. **Handle None returns** - query methods return `Optional` types

See: [Best Practices](database-schema.md#best-practices)

## Database Statistics

These counts drift easily, so this landing page no longer carries them. Canonical sources: the table inventory in [database-schema.md](database-schema.md), the migration files in [`internal/database/migrations/versions/`](../internal/database/migrations/versions/), and the repository signatures in [database-schema-llm.md](database-schema-llm.md#database-operations).

## Contributing

When modifying the database schema:

1. Create a new migration file with incremented version number
2. Update both documentation files:
   - [`database-schema.md`](database-schema.md) - Full technical details
   - [`database-schema-llm.md`](database-schema-llm.md) - Concise reference
3. Update TypedDict models in [`internal/database/models.py`](../internal/database/models.py:1)
4. Add corresponding methods to the appropriate repository in [`internal/database/repositories/`](../internal/database/repositories/)
5. Test migrations on all configured data sources

## License

This documentation is part of the Gromozeka bot project.

---

**Last Updated**: 2026-08-26
**Database Version**: 29
**Documentation Version**: 2.4