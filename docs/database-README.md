# Database Documentation

Welcome to the Gromozeka bot's database documentation. This directory contains comprehensive documentation for the database schema and operations.

> **Canonical sources.** This file is a landing-page overview; for authoritative
> schema details, see [`database-schema.md`](database-schema.md) (human-facing)
> and [`database-schema-llm.md`](database-schema-llm.md) (LLM-facing). Counts
> and method signatures are maintained as of the latest audit; when in doubt
> against code, the schema docs are authoritative.


## 📚 Documentation Files

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

## 🗂️ Quick Navigation

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
- [`webhook_updates`](database-schema.md#webhook_updates) - Max webhook payload buffer (two-process webhook mode)

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

## 🔍 Key Features

### SQL Portability
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
- **Repository pattern**: Organized access through 16 specialized repositories

Learn more: [TypedDict Models](database-schema.md#typeddict-models)

## 🔌 SQL Portability

### Overview

The Gromozeka database system is designed to work with multiple relational database management systems (RDBMS) through a provider abstraction layer. This allows you to choose the database that best fits your needs and switch between them with minimal code changes.

### Supported Database Providers

#### SQLite (Default)
- **Provider**: [`SQLite3Provider`](../lib/db/providers/sqlite3.py:1)
- **Library**: `aiosqlite` (async wrapper over Python's `sqlite3` stdlib module)
- **Use case**: Embedded databases, development, testing, small to medium deployments
- **Features**: Zero configuration, file-based, ACID compliant, optional `sqlite-vec` extension for native vector search
- **Status**: Registered in `getSqlProvider` factory

#### MySQL
- **Provider**: [`MySQLProvider`](../lib/db/providers/mysql.py:1)
- **Library**: `aiomysql` (async MySQL driver)
- **Use case**: Production deployments, high concurrency, large datasets
- **Features**: Connection pooling, async operations, enterprise-grade
- **Status**: Implemented but **not yet registered** in the `getSqlProvider` factory; cannot be selected via config today

#### PostgreSQL
- **Provider**: [`PostgreSQLProvider`](../lib/db/providers/postgresql.py:1)
- **Library**: `asyncpg` (async PostgreSQL driver)
- **Use case**: Production deployments, complex queries, advanced features
- **Features**: Connection pooling, async operations, rich data types
- **Status**: Implemented but **not yet registered** in the `getSqlProvider` factory; cannot be selected via config today

#### SQLink
- **Provider**: [`SQLinkProvider`](../lib/db/providers/sqlink.py:1)
- **Library**: `sqlink` (HTTP client for a remote SQLink database server)
- **Use case**: Remote database operations via a SQLink HTTP server (with optional HTTP/HTTPS proxy)
- **Features**: Async operations, HTTP-based remote access, proxy support
- **Status**: Registered in `getSqlProvider` factory

### Provider Methods

The `BaseSQLProvider` class defines a common interface that all providers implement. Key methods for SQL portability:

#### `upsert()`
Perform an "insert or update" operation with provider-specific SQL syntax.

```python
from internal.database.providers.base import ExcludedValue

# Insert or update a chat message
await db.chatMessages.saveChatMessage(
    date=datetime.now(),
    chatId=-1001234567890,
    userId=123456789,
    messageId="12345",
    messageText="Hello, world!",
    messageType=MessageType.TEXT,
    messageCategory=MessageCategory.USER
)

# The provider automatically handles the upsert syntax:
# - SQLite/PostgreSQL: INSERT ... ON CONFLICT DO UPDATE
# - MySQL: INSERT ... ON DUPLICATE KEY UPDATE
```

#### `getCaseInsensitiveComparison()`
Generate a case-insensitive equality comparison SQL expression.

The method returns a complete SQL expression fragment that compares a column
against a bound parameter using case-insensitive semantics:

```python
# Case-insensitive exact match search
expr = provider.getCaseInsensitiveComparison("name_en", "searchName")
# Returns: 'LOWER(name_en) = LOWER(:searchName)' for SQLite/PostgreSQL/SQLink
# Returns: 'name_en COLLATE utf8mb4_general_ci = :searchName' for MySQL
```

**Key details:**
- Takes two arguments: `column` (column name) and `param` (parameter name, without the `:` prefix)
- Returns a complete SQL expression, not just an operator — ready to embed in a WHERE clause
- SQLite, PostgreSQL, and SQLink use `LOWER(column) = LOWER(:param)`
- MySQL uses `column COLLATE utf8mb4_general_ci = :param`

#### `getLikeComparison()`
Get a complete SQL LIKE expression for case-insensitive pattern matching. Takes a column name and a parameter name, and returns a full expression suitable for embedding in a WHERE clause.

```python
# Case-insensitive fuzzy search
expression = provider.getLikeComparison('name', 'search')
# Returns: "LOWER(name) LIKE LOWER(:search)" for SQLite / SQLink / MySQL / PostgreSQL
# (All current implementations use the LOWER/LIKE shape; PostgreSQL does NOT use ILIKE,
# to keep the expression portable across providers.)
```

**Use cases:**
- Fuzzy/partial text search (e.g., searching layout names in divinations)
- Type-ahead functionality where user input is incomplete
- Pattern matching across different RDBMS

**Example:**
```python
# Fuzzy search for layout name
query = f"SELECT * FROM layouts WHERE {provider.getLikeComparison('name', 'search')}"
# Executes as: SELECT * FROM layouts WHERE LOWER(name) LIKE LOWER(:search)
# With parameter: search = "%three card%"
```

#### `applyPagination()`
Apply pagination to a query with provider-specific syntax.

```python
# Paginated query
query = "SELECT * FROM chat_messages WHERE chatId = ?"
paginatedQuery = provider.applyPagination(query, limit=50, offset=100)
# Returns: 'SELECT * FROM chat_messages WHERE chatId = ? LIMIT 50 OFFSET 100' for SQLite/SQLink/MySQL/PostgreSQL
# (All current implementations use the same 'LIMIT {limit} OFFSET {offset}' shape.)
```

#### `getTextType()`
Get the appropriate text data type for the provider.

```python
# Schema migrations
textType = provider.getTextType()
# Returns: 'TEXT' for SQLite / SQLink / PostgreSQL
# Returns: 'TEXT' for MySQL (or 'MEDIUMTEXT' / 'LONGTEXT' when maxLength exceeds 64KB / 16MB)
```

### The `ExcludedValue` Class

The `ExcludedValue` class is a special marker that allows provider-specific translation of upsert update expressions:

```python
from internal.database.providers.base import ExcludedValue

# In an upsert operation, use ExcludedValue to reference the new value
update_expressions = {
    "value": ExcludedValue(),  # Will be translated to excluded.value or VALUES(value)
    "count": "count + 1"  # Custom expression
}

# Provider-specific translation:
# - SQLite/PostgreSQL: excluded.column
# - MySQL: VALUES(column)
```

### Configuration Examples

> **Schema note.** The configuration key is `[database.providers.<name>]`
> (not `sources`), with a `provider = "..."` field selecting the provider
> class and a `[database.providers.<name>.parameters]` sub-table for
> constructor kwargs. See `configs/00-defaults/00-config.toml` for the
> live default.

#### MySQL Configuration

```toml
[database.providers.mysql_primary]
provider = "mysql"
host = "localhost"
port = 3306
user = "gromozeka"
password = "your_password"
database = "gromozeka_db"
readOnly = false

[database.providers.mysql_primary.parameters]
keepConnection = false  # Connect on demand (default for MySQL)
```

#### PostgreSQL Configuration

```toml
[database.providers.postgres_primary]
provider = "postgresql"
host = "localhost"
port = 5432
user = "gromozeka"
password = "your_password"
database = "gromozeka_db"
readOnly = false

[database.providers.postgres_primary.parameters]
keepConnection = false  # Connect on demand (default for PostgreSQL)
```

#### SQLite Configuration (Default)

```toml
[database.providers.sqlite_primary]
provider = "sqlite3"
# Constructor kwargs go under [parameters]; key names match SQLite3Provider.__init__:
#   dbPath, readOnly, useWal, timeout, enableForeignKeys, keepConnection, vectorExtensionPath
[database.providers.sqlite_primary.parameters]
dbPath = "bot.db"
readOnly = false
timeout = 30
enableForeignKeys = true
keepConnection = false  # Connect on demand (default for file-based SQLite)
# For in-memory SQLite, use: keepConnection = true
```

### Database-Specific Considerations

#### SQLite
- **Foreign keys**: Must be enabled with `PRAGMA foreign_keys = ON` (handled by `enableForeignKeys` parameter, defaults to `True`)
- **Date/time**: Application code sets timestamps explicitly (no `DEFAULT CURRENT_TIMESTAMP` — see [SQL Portability Guide](sql-portability-guide.md))
- **Case sensitivity**: `getCaseInsensitiveComparison()` uses `LOWER(column) = LOWER(:param)` (not `COLLATE NOCASE`)
- **Pagination**: Uses `LIMIT {limit} OFFSET {offset}` syntax
- **Upsert**: Uses `INSERT ... ON CONFLICT DO UPDATE` syntax
- **Connection management**: In-memory databases (`:memory:`) default to `keepConnection=True` to prevent data loss

#### MySQL
- **Connection pooling**: Uses `aiomysql.Pool` for connection management
- **Date/time**: Application code sets timestamps explicitly (no `DEFAULT CURRENT_TIMESTAMP`)
- **Case sensitivity**: `getCaseInsensitiveComparison()` uses `column COLLATE utf8mb4_general_ci = :param`; `getLikeComparison()` uses `LOWER(column) LIKE LOWER(:param)`
- **Pagination**: Uses `LIMIT {limit} OFFSET {offset}` syntax (same shape as the other providers; not MySQL's positional `LIMIT offset, limit` form)
- **Upsert**: Uses `INSERT ... ON DUPLICATE KEY UPDATE` syntax
- **Connection management**: Defaults to `keepConnection=False` (connect on demand)

#### PostgreSQL
- **Connection pooling**: Uses `asyncpg.Pool` for connection management
- **Date/time**: Application code sets timestamps explicitly (no `DEFAULT CURRENT_TIMESTAMP`)
- **Case sensitivity**: `getCaseInsensitiveComparison()` and `getLikeComparison()` use `LOWER(column) [LIKE] LOWER(:param)` (not `ILIKE`, for cross-provider portability)
- **Pagination**: Uses `LIMIT {limit} OFFSET {offset}` syntax
- **Upsert**: Uses `INSERT ... ON CONFLICT DO UPDATE` syntax
- **Connection management**: Defaults to `keepConnection=False` (connect on demand)

### Migration Between Providers

To switch between database providers:

1. **Update configuration**: Change the provider type in your config file
2. **Run migrations**: The migration system will create the schema in the new database
3. **Migrate data**: Use database-specific tools to migrate data (e.g., `pg_dump` for PostgreSQL)
4. **Test thoroughly**: Ensure all operations work correctly with the new provider

### Best Practices

1. **Use provider methods**: Always use provider methods instead of raw SQL for portable operations
2. **Test on all providers**: Ensure your code works with all supported providers
3. **Handle provider-specific features**: Use conditional logic for features that differ between providers
4. **Document provider dependencies**: Note any provider-specific requirements in your code
5. **Use parameterized queries**: Always use parameterized queries to prevent SQL injection

### Related Documentation

- **SQL Portability Guide**: [`sql-portability-guide.md`](sql-portability-guide.md)
- **Provider Base Class**: [`lib/db/providers/base.py`](../lib/db/providers/base.py:1)
- **SQLite Provider**: [`lib/db/providers/sqlite3.py`](../lib/db/providers/sqlite3.py:1)
- **MySQL Provider**: [`lib/db/providers/mysql.py`](../lib/db/providers/mysql.py:1)
- **PostgreSQL Provider**: [`lib/db/providers/postgresql.py`](../lib/db/providers/postgresql.py:1)
- **SQLink Provider**: [`lib/db/providers/sqlink.py`](../lib/db/providers/sqlink.py:1)

### Repository Pattern Architecture

The database system uses a repository pattern with 16 specialized repositories, each responsible for a specific domain of data operations:

#### Available Repositories

1. **[`chatMessages`](../internal/database/repositories/chat_messages.py:1)** - Message storage and retrieval
   - `saveChatMessage()` - Store new messages
   - `getChatMessageByMessageId()` - Fetch specific message
   - `getChatMessagesSince()` - Retrieve messages by date range
   - `getChatMessagesByRootId()` - Get messages in a thread
   - `getChatMessagesByUser()` - Get messages by user
   - `getMessageThread()` - Fetch a message thread

2. **[`chatUsers`](../internal/database/repositories/chat_users.py:1)** - User information management
   - `updateChatUser()` - Store/update user data
   - `getChatUser()` - Retrieve user information
   - `getChatUsers()` - List users in a chat
   - `getChatUserByUsername()` - Look up user by username

3. **[`chatInfo`](../internal/database/repositories/chat_info.py:1)** - Chat metadata operations
   - `updateChatInfo()` - Store chat information
   - `getChatInfo()` - Retrieve chat metadata
   - `updateChatTopicInfo()` - Store forum topic data
   - `getChatTopics()` - List forum topics

4. **[`chatSettings`](../internal/database/repositories/chat_settings.py:1)** - Configuration management
   - `getChatSettings()` - Get all settings for a chat
   - `getChatSetting()` - Get specific setting value
   - `setChatSetting()` - Update a setting
   - `unsetChatSetting()` - Remove a setting

5. **[`chatSummarization`](../internal/database/repositories/chat_summarization.py:1)** - Summary caching
   - `addChatSummarization()` - Store a chat summary
   - `getChatSummarization()` - Retrieve cached summaries

6. **[`mediaAttachments`](../internal/database/repositories/media_attachments.py:1)** - Media file tracking
   - `addMediaAttachment()` - Store media metadata
   - `updateMediaAttachment()` - Update media metadata
   - `getMediaAttachment()` - Retrieve media information
   - `getMediaAttachmentsByGroupId()` - Get media by group ID

7. **[`spam`](../internal/database/repositories/spam.py:1)** - Spam detection
   - `addSpamMessage()` - Track spam messages
   - `addHamMessage()` - Track legitimate messages
   - `getSpamMessages()` - Get recorded spam messages

8. **[`delayedTasks`](../internal/database/repositories/delayed_tasks.py:1)** - Task scheduling
   - `addDelayedTask()` - Schedule a task
   - `getPendingDelayedTasks()` - Retrieve pending tasks
   - `updateDelayedTask()` - Mark a task as done
   - `cleanupOldCompletedDelayedTasks()` - Remove old completed tasks

9. **[`cache`](../internal/database/repositories/cache.py:1)** - Generic caching
   - `setCacheEntry()` - Store a cached value
   - `getCacheEntry()` - Retrieve a cached value
   - `clearCache()` - Remove cache entries by type
   - `getCacheStorage()` - List storage namespaces
   - `setCacheStorage()` - Set a storage namespace

10. **[`common`](../internal/database/repositories/common.py:1)** - Common operations
    - `getSettings()` - Get global system settings
    - `getSetting()` - Get a specific setting
    - `setSetting()` - Update a system setting

11. **[`chatSearch`](../internal/database/repositories/chat_search.py:1)** - Chat message search
    - `searchChatMessages()` - Search messages (filter-only or semantic)

12. **[`chatEmbeddings`](../internal/database/repositories/chat_embeddings.py:1)** - Message embedding vectors
   - `saveMessageEmbedding()` - Store message embedding (writes vec0 row only; the model provenance is recorded in `chat_messages.model_id` via the injected `modelIdResolver`)
   - `deleteObsoleteModelEmbeddings()` - Drop stale vec0 families for a model that no longer has any embeddings
   - `getMessagesWithoutEmbeddings()` - Find messages needing embeddings

13. **[`divinations`](../internal/database/repositories/divinations.py:1)** - Divination readings and layouts
   - `insertReading()` - Save a divination reading
   - `getLayout()` - Retrieve a cached layout definition
   - `saveLayout()` - Cache a layout definition
   - `saveNegativeCache()` - Cache negative result (layout not found)

14. **[`userMemories`](../internal/database/repositories/user_memories.py:1)** - Unified per-(chat, user, thread) structured memory store
   - `addMemory()` - Store a memory entry (permanent or ephemeral)
   - `getMemory()` - Fetch a single memory by id
   - `getPermanentMemories()` - List permanent memories for a (chat, user, thread)
   - `getLatestMemories()` - List most-recent memories
   - `searchMemories()` - Search memories (filter-only or semantic)
   - `deleteMemory()` - Soft-delete a memory entry
   - `saveMemoryEmbedding()` - Store a memory embedding vector (model provenance resolved internally to `model_id` via the injected `modelIdResolver`; handler signature stays model-agnostic)
   - `getMemoriesWithoutEmbeddings()` - Backfill helper for missing embeddings

15. **[`webhookUpdates`](../internal/database/repositories/webhook_updates.py:1)** - Max webhook payload buffer (two-process webhook mode; see ADR-013)
   - `addUpdate()` - Enqueue an incoming webhook payload
   - `getUnprocessedUpdates()` - Pull pending payloads for consumption
   - `markProcessed()` - Mark payloads as consumed
   - `markProcessedBeforeMarker()` - Bulk-mark up to a marker
   - `deleteProcessedOlderThan()` - Reap old processed payloads

16. **[`embedding_models`](../internal/database/repositories/embedding_models.py:1)** - Embedding-model provenance lookup (process-local cache; injected as `modelIdResolver` into `chatEmbeddings`, `chatSearch`, and `userMemories`)
   - `getOrCreateModelId()` - Resolve `(model, dimensions)` to a stable `model_id`, inserting a row on first sight
   - `getModelById()` - Reverse lookup `model_id` → `ModelDict`
   - `listModels()` - Enumerate all registered models

#### Accessing Repositories

All repositories are accessed through the main `Database` instance:

```python
# Access repositories via the db instance
await db.chatMessages.saveChatMessage(...)
await db.chatSettings.getChatSetting(...)
```

Each repository is automatically initialized when the `Database` class is instantiated and provides type-safe access to its domain-specific operations.

## 🚀 Getting Started

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

## 📖 Usage Examples

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
```python
# Explicit source routing
messages = await db.chatMessages.getChatMessagesSince(chatId=123, dataSource="archive")

# Chat mapping routing (configured in config.toml)
messages = await db.chatMessages.getChatMessagesSince(chatId=-1001234567890)  # Routes to mapped source

# Default routing
messages = await db.chatMessages.getChatMessagesSince(chatId=456)  # Routes to default source
```

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

### Cache Operations
```python
from internal.database.models import CacheType

# Set cache value
await db.cache.setCacheEntry(
    key='weather-123',
    data='{"temp": 20}',
    cacheType=CacheType.WEATHER,
)

# Get cache value
cachedData = await db.cache.getCacheEntry(
    key='weather-123',
    cacheType=CacheType.WEATHER,
    ttl=3600
)
```

### SQL Portability Examples

#### Using Provider Methods
```python
# Access the provider for the current data source
provider = await db.manager.getProvider(dataSource="primary")

# Apply pagination
query = "SELECT * FROM chat_messages WHERE chatId = ?"
paginatedQuery = provider.applyPagination(query, limit=50, offset=100)
# Returns provider-specific pagination syntax

# Case-insensitive exact match search
expr = provider.getCaseInsensitiveComparison("name", "searchName")
# Returns: 'LOWER(name) = LOWER(:searchName)' for SQLite/PostgreSQL/SQLink
# Returns: 'name COLLATE utf8mb4_general_ci = :searchName' for MySQL
```

#### Cross-Provider Upsert
```python
from internal.database.providers.base import ExcludedValue

# Upsert operation works the same across all providers
await db.chatMessages.saveChatMessage(
    date=datetime.now(),
    chatId=-1001234567890,
    userId=123456789,
    messageId="12345",
    messageText="Hello, world!",
    messageType=MessageType.TEXT,
    messageCategory=MessageCategory.USER
)

# The provider automatically handles the upsert syntax:
# - SQLite: INSERT ... ON CONFLICT DO UPDATE
# - MySQL: INSERT ... ON DUPLICATE KEY UPDATE
# - PostgreSQL: INSERT ... ON CONFLICT DO UPDATE
```

#### Provider-Specific Configuration
```toml
# SQLite with foreign keys enabled
[database.providers.sqlite]
provider = "sqlite3"

[database.providers.sqlite.parameters]
dbPath = "bot.db"
enableForeignKeys = true  # SQLite-specific option

# MySQL (provider class exists; not yet selectable in getSqlProvider)
[database.providers.mysql]
provider = "mysql"
host = "localhost"
port = 3306
user = "gromozeka"
password = "password"
database = "gromozeka_db"

# PostgreSQL (provider class exists; not yet selectable in getSqlProvider)
[database.providers.postgres]
provider = "postgresql"
host = "localhost"
port = 5432
user = "gromozeka"
password = "password"
database = "gromozeka_db"
```

## 🔗 Related Documentation

- **Database Class**: [`internal/database/database.py`](../internal/database/database.py:1)
- **Database Manager**: [`lib/db/manager.py`](../lib/db/manager.py:1)
- **Repository Base Class**: [`internal/database/repositories/base.py`](../internal/database/repositories/base.py:1)
- **Database Models**: [`internal/database/models.py`](../internal/database/models.py:1)
- **Migration Manager**: [`internal/database/migrations/manager.py`](../internal/database/migrations/manager.py:59)
- **Migration Base Class**: [`internal/database/migrations/base.py`](../internal/database/migrations/base.py:41)
- **Chat Settings Keys**: [`internal/bot/models/chat_settings.py`](../internal/bot/models/chat_settings.py:281)

## 🛠️ Development Guidelines

### Creating New Migrations

1. Create file: `internal/database/migrations/versions/migration_XXX_description.py`
2. Implement `BaseMigration` class with `version`, `description`, `up()`, and `down()` methods
3. Add `getMigration()` function returning the migration class
4. The migration will be auto-discovered on next startup

See: [Creating New Migrations](database-schema.md#creating-new-migrations)

### Best Practices

1. **Always use context managers** for database operations
2. **Specify chatId** for operations that support multi-source routing
3. **Use TypedDict types** for type-safe returns
4. **Check return values** - most operations return `bool` for success/failure
5. **Handle None returns** - query methods return `Optional` types

See: [Best Practices](database-schema.md#best-practices)

## 📊 Database Statistics

> These counts drift easily. For the canonical, up-to-date table list see
> [`database-schema.md`](database-schema.md); for migration files see
> [`internal/database/migrations/versions/`](../internal/database/migrations/versions/).

- **Total Tables**: 25+ base tables (plus dynamic vec0 tables per embedding dimension and per-`CacheType` cache tables)
- **Core Tables**: 5 (`chat_messages`, `chat_users`, `chat_info`, `chat_topics`, `chat_settings`)
- **Cache Tables**: 3 explicit (`chat_summarization_cache`, `cache_storage`, `cache`) plus dynamic per-`CacheType` tables
- **Spam Detection Tables**: 4 (`spam_messages`, `ham_messages`, `bayes_tokens`, `bayes_classes`)
- **Statistics Tables**: 2 (`stat_events`, `stat_aggregates`) — legacy `chat_stats` and `chat_user_stats` dropped in migration_027
- **Current Migration Version**: 28
- **Total Repositories**: 16 specialised repositories on the `Database` class

## 🤝 Contributing

When modifying the database schema:

1. Create a new migration file with incremented version number
2. Update both documentation files:
   - [`database-schema.md`](database-schema.md) - Full technical details
   - [`database-schema-llm.md`](database-schema-llm.md) - Concise reference
3. Update TypedDict models in [`internal/database/models.py`](../internal/database/models.py:1)
4. Add corresponding methods to the appropriate repository in [`internal/database/repositories/`](../internal/database/repositories/)
5. Test migrations on all configured data sources

## 📝 License

This documentation is part of the Gromozeka bot project.

---

**Last Updated**: 2026-07-21
**Database Version**: 25
**Documentation Version**: 2.4