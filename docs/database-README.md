# Database Documentation

Welcome to the Gromozeka bot's database documentation. This directory contains comprehensive documentation for the database schema and operations.

> **Note**: SQL portability implementation is now complete! All 5 phases have been implemented, enabling cross-RDBMS compatibility with SQLite, MySQL, PostgreSQL, and SQLink providers. See [SQL Portability Implementation Status](reports/sql-portability-implementation-status.md) for details.

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
- [`chat_stats`](database-schema.md#chat_stats) - Daily chat statistics
- [`chat_user_stats`](database-schema.md#chat_user_stats) - Daily per-user statistics

#### Media Tables
- [`media_attachments`](database-schema.md#media_attachments) - Media file information

#### User Data Tables
- [`user_data`](database-schema.md#user_data) - Arbitrary user key-value data

#### Spam Detection Tables
- [`spam_messages`](database-schema.md#spam_messages) - Spam message tracking
- [`ham_messages`](database-schema.md#ham_messages) - Legitimate message tracking
- [`bayes_tokens`](database-schema.md#bayes_tokens) - Bayesian filter token statistics
- [`bayes_classes`](database-schema.md#bayes_classes) - Bayesian filter class statistics

#### Cache Tables
- [`chat_summarization_cache`](database-schema.md#chat_summarization_cache) - Cached summaries
- [`cache_storage`](database-schema.md#cache_storage) - Generic key-value cache
- [Dynamic Cache Tables](database-schema.md#dynamic-cache-tables) - API response caching

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
- **Multiple providers**: SQLite, MySQL, PostgreSQL, and SQLink
- **Provider abstraction**: Common interface through `BaseSQLProvider` class
- **Portable operations**: Provider-specific methods handle SQL dialect differences
- **Type safety**: Consistent TypedDict models across all providers
- **Easy migration**: Switch between databases with minimal code changes

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
- **Repository pattern**: Organized access through 12 specialized repositories

Learn more: [TypedDict Models](database-schema.md#typeddict-models)

## 🔌 SQL Portability

### Overview

The Gromozeka database system is designed to work with multiple relational database management systems (RDBMS) through a provider abstraction layer. This allows you to choose the database that best fits your needs and switch between them with minimal code changes.

### Supported Database Providers

#### SQLite (Default)
- **Provider**: [`SQLite3Provider`](../internal/database/providers/sqlite3.py:1)
- **Library**: `sqlite3` (Python standard library)
- **Use case**: Embedded databases, development, testing, small to medium deployments
- **Features**: Zero configuration, file-based, ACID compliant

#### MySQL
- **Provider**: [`MySQLProvider`](../internal/database/providers/mysql.py:1)
- **Library**: `aiomysql` (async MySQL driver)
- **Use case**: Production deployments, high concurrency, large datasets
- **Features**: Connection pooling, async operations, enterprise-grade

#### PostgreSQL
- **Provider**: [`PostgreSQLProvider`](../internal/database/providers/postgresql.py:1)
- **Library**: `asyncpg` (async PostgreSQL driver)
- **Use case**: Production deployments, complex queries, advanced features
- **Features**: Connection pooling, async operations, rich data types

#### SQLink
- **Provider**: [`SQLinkProvider`](../internal/database/providers/sqlink.py:1)
- **Library**: `sqlink` (SQLite with async support)
- **Use case**: Async SQLite operations, better performance than sqlite3
- **Features**: Async operations, SQLite compatibility

### Provider Methods

The `BaseSQLProvider` class defines a common interface that all providers implement. Key methods for SQL portability:

#### `upsert()`
Perform an "insert or update" operation with provider-specific SQL syntax.

```python
from internal.database.providers.base import ExcludedValue

# Insert or update a chat message
db.chatMessages.saveChatMessage(
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

#### `getCurrentTimestamp()`
Get the current timestamp in the provider's native format.

```python
# Provider-specific timestamp handling
timestamp = provider.getCurrentTimestamp()
# Returns: 'datetime("now")' for SQLite
# Returns: 'NOW()' for MySQL
# Returns: 'NOW()' for PostgreSQL
```

#### `getCaseInsensitiveComparison()`
Get the SQL operator for case-insensitive string comparison.

```python
# Case-insensitive search
operator = provider.getCaseInsensitiveComparison()
# Returns: 'LIKE' for SQLite
# Returns: 'LIKE' for MySQL
# Returns: 'ILIKE' for PostgreSQL
```

#### `getLikeComparison()`
Get the SQL operator for case-insensitive LIKE pattern matching.

```python
# Case-insensitive fuzzy search
operator = provider.getLikeComparison()
# Returns: 'LOWER(column) LIKE LOWER(:param)' for SQLite
# Returns: 'LOWER(column) LIKE LOWER(:param)' for MySQL
# Returns: 'LOWER(column) LIKE LOWER(:param)' for PostgreSQL (or ILIKE)
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
# Returns: 'SELECT * FROM chat_messages WHERE chatId = ? LIMIT 50 OFFSET 100' for SQLite/PostgreSQL
# Returns: 'SELECT * FROM chat_messages WHERE chatId = ? LIMIT 100, 50' for MySQL
```

#### `getTextType()`
Get the appropriate text data type for the provider.

```python
# Schema migrations
textType = provider.getTextType()
# Returns: 'TEXT' for SQLite
# Returns: 'VARCHAR(255)' for MySQL
# Returns: 'TEXT' for PostgreSQL
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

#### MySQL Configuration

```toml
[database.sources.mysql_primary]
type = "mysql"
host = "localhost"
port = 3306
user = "gromozeka"
password = "your_password"
database = "gromozeka_db"
readonly = false
pool-size = 10
timeout = 30

[database.sources.mysql_primary.parameters]
keepConnection = false  # Connect on demand (default for MySQL)
```

#### PostgreSQL Configuration

```toml
[database.sources.postgres_primary]
type = "postgresql"
host = "localhost"
port = 5432
user = "gromozeka"
password = "your_password"
database = "gromozeka_db"
readonly = false
pool-size = 10
timeout = 30

[database.sources.postgres_primary.parameters]
keepConnection = false  # Connect on demand (default for PostgreSQL)
```

#### SQLite Configuration (Default)

```toml
[database.sources.sqlite_primary]
type = "sqlite3"
path = "bot.db"
readonly = false
pool-size = 10
timeout = 30
enable_foreign_keys = true  # SQLite-specific option

[database.sources.sqlite_primary.parameters]
keepConnection = false  # Connect on demand (default for file-based SQLite)
# For in-memory SQLite, use: keepConnection = true
```

### Database-Specific Considerations

#### SQLite
- **Foreign keys**: Must be enabled with `PRAGMA foreign_keys = ON` (handled by `enable_foreign_keys` parameter)
- **Date/time**: Uses `datetime("now")` for current timestamp
- **Case sensitivity**: Uses `LIKE` for case-insensitive comparison
- **Pagination**: Uses `LIMIT ? OFFSET ?` syntax
- **Upsert**: Uses `INSERT ... ON CONFLICT DO UPDATE` syntax
- **Connection management**: In-memory databases (`:memory:`) default to `keepConnection=true` to prevent data loss

#### MySQL
- **Connection pooling**: Uses `aiomysql.Pool` for connection management
- **Date/time**: Uses `NOW()` for current timestamp
- **Case sensitivity**: Uses `LIKE` for case-insensitive comparison
- **Pagination**: Uses `LIMIT ?, ?` syntax (offset, limit)
- **Upsert**: Uses `INSERT ... ON DUPLICATE KEY UPDATE` syntax
- **Connection management**: Defaults to `keepConnection=false` (connect on demand)

#### PostgreSQL
- **Connection pooling**: Uses `asyncpg.Pool` for connection management
- **Date/time**: Uses `NOW()` for current timestamp
- **Case sensitivity**: Uses `ILIKE` for case-insensitive comparison
- **Pagination**: Uses `LIMIT ? OFFSET ?` syntax
- **Upsert**: Uses `INSERT ... ON CONFLICT DO UPDATE` syntax
- **Connection management**: Defaults to `keepConnection=false` (connect on demand)

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
- **Provider Base Class**: [`internal/database/providers/base.py`](../internal/database/providers/base.py:1)
- **SQLite Provider**: [`internal/database/providers/sqlite3.py`](../internal/database/providers/sqlite3.py:1)
- **MySQL Provider**: [`internal/database/providers/mysql.py`](../internal/database/providers/mysql.py:1)
- **PostgreSQL Provider**: [`internal/database/providers/postgresql.py`](../internal/database/providers/postgresql.py:1)
- **SQLink Provider**: [`internal/database/providers/sqlink.py`](../internal/database/providers/sqlink.py:1)

### Repository Pattern Architecture

The database system uses a repository pattern with 12 specialized repositories, each responsible for a specific domain of data operations:

#### Available Repositories

1. **[`chatMessages`](../internal/database/repositories/chat_messages.py:1)** - Message storage and retrieval
   - `saveChatMessage()` - Store new messages
   - `getChatMessageByMessageId()` - Fetch specific message
   - `getChatMessagesSince()` - Retrieve messages by date range
   - `getChatMessages()` - Get messages with filtering

2. **[`chatUsers`](../internal/database/repositories/chat_users.py:1)** - User information management
   - `saveChatUser()` - Store/update user data
   - `getChatUser()` - Retrieve user information
   - `getChatUsers()` - List users in a chat

3. **[`chatInfo`](../internal/database/repositories/chat_info.py:1)** - Chat metadata operations
   - `saveChatInfo()` - Store chat information
   - `getChatInfo()` - Retrieve chat metadata
   - `saveTopic()` - Store forum topics

4. **[`chatSettings`](../internal/database/repositories/chat_settings.py:1)** - Configuration management
   - `getChatSettings()` - Get all settings for a chat
   - `getChatSetting()` - Get specific setting value
   - `setChatSetting()` - Update a setting

5. **[`chatSummarization`](../internal/database/repositories/chat_summarization.py:1)** - Summary caching
   - `getChatSummarizationCache()` - Retrieve cached summaries
   - `setChatSummarizationCache()` - Store summary cache

6. **[`userData`](../internal/database/repositories/user_data.py:1)** - User key-value storage
   - `setUserData()` - Store user-specific data
   - `getUserData()` - Retrieve user data
   - `deleteUserData()` - Remove user data

7. **[`mediaAttachments`](../internal/database/repositories/media_attachments.py:1)** - Media file tracking
   - `saveMediaAttachment()` - Store media metadata
   - `getMediaAttachment()` - Retrieve media information

8. **[`spam`](../internal/database/repositories/spam.py:1)** - Spam detection
   - `saveSpamMessage()` - Track spam messages
   - `saveHamMessage()` - Track legitimate messages
   - `getBayesToken()` - Get token statistics

9. **[`delayedTasks`](../internal/database/repositories/delayed_tasks.py:1)** - Task scheduling
   - `saveDelayedTask()` - Schedule a task
   - `getDelayedTasks()` - Retrieve pending tasks
   - `deleteDelayedTask()` - Remove completed tasks

10. **[`cache`](../internal/database/repositories/cache.py:1)** - Generic caching
    - `setCache()` - Store cached data
    - `getCache()` - Retrieve cached data
    - `deleteCache()` - Remove cache entries

11. **[`common`](../internal/database/repositories/common.py:1)** - Common operations
    - `getSettings()` - Get global system settings
    - `setSettings()` - Update system settings

12. **[`base`](../internal/database/repositories/base.py:1)** - Base repository class
    - Provides common functionality for all repositories
    - Handles database connection management
    - Implements multi-source routing logic

#### Accessing Repositories

All repositories are accessed through the main `Database` instance:

```python
# Access repositories via the db instance
db.chatMessages.saveChatMessage(...)
db.chatSettings.getChatSetting(...)
db.userData.setUserData(...)
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
db.chatMessages.saveChatMessage(
    date=datetime.now(),
    chatId=-1001234567890,
    userId=123456789,
    messageId="12345",
    messageText="Hello, world!",
    messageType=MessageType.TEXT,
    messageCategory=MessageCategory.USER
)

# Retrieve recent messages
messages = db.chatMessages.getChatMessagesSince(
    chatId=-1001234567890,
    sinceDateTime=datetime.now() - timedelta(hours=1),
    limit=50
)

# Get a specific message by ID
message = db.chatMessages.getChatMessageByMessageId(
    chatId=-1001234567890,
    messageId="12345"
)
```

### Multi-Source Routing
```python
# Explicit source routing
messages = db.chatMessages.getChatMessages(chatId=123, dataSource="archive")

# Chat mapping routing (configured in config.toml)
messages = db.chatMessages.getChatMessages(chatId=-1001234567890)  # Routes to mapped source

# Default routing
messages = db.chatMessages.getChatMessages(chatId=456)  # Routes to default source
```

### Chat Settings Management
```python
# Get all settings for a chat
settings = db.chatSettings.getChatSettings(chatId=-1001234567890)
# Returns Dict[str, tuple[str, int]] where tuple is (value, updated_by)
model = settings.get('chat-model', ('gpt-4', 0))[0]  # Index [0] for value

# Set a specific setting
db.chatSettings.setChatSetting(
    chatId=-1001234567890,
    key='parse-images',
    value='true',
    updatedBy=userId  # REQUIRED keyword-only argument
)

# Get a specific setting value
settingValue = db.chatSettings.getChatSetting(
    chatId=-1001234567890,
    key='parse-images'
)
```

### User Data Operations
```python
# Save user data
db.userData.setUserData(
    chatId=-1001234567890,
    userId=123456789,
    key='preference',
    value='dark-mode'
)

# Get user data
userData = db.userData.getUserData(
    chatId=-1001234567890,
    userId=123456789,
    key='preference'
)
```

### Cache Operations
```python
# Set cache value
db.cache.setCache(
    cacheType='api_response',
    key='weather-123',
    value='{"temp": 20}',
    ttl=3600
)

# Get cache value
cachedData = db.cache.getCache(
    cacheType='api_response',
    key='weather-123'
)
```

### SQL Portability Examples

#### Using Provider Methods
```python
# Access the provider for the current data source
provider = db.getProvider(dataSource="primary")

# Get provider-specific timestamp
timestamp = provider.getCurrentTimestamp()
# Returns provider-specific timestamp function

# Apply pagination
query = "SELECT * FROM chat_messages WHERE chatId = ?"
paginatedQuery = provider.applyPagination(query, limit=50, offset=100)
# Returns provider-specific pagination syntax

# Case-insensitive search
operator = provider.getCaseInsensitiveComparison()
# Returns 'LIKE' for SQLite/MySQL, 'ILIKE' for PostgreSQL
```

#### Cross-Provider Upsert
```python
from internal.database.providers.base import ExcludedValue

# Upsert operation works the same across all providers
db.chatMessages.saveChatMessage(
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
[database.sources.sqlite]
type = "sqlite3"
path = "bot.db"
enable_foreign_keys = true  # SQLite-specific option

# MySQL with connection pooling
[database.sources.mysql]
type = "mysql"
host = "localhost"
port = 3306
user = "gromozeka"
password = "password"
database = "gromozeka_db"
pool-size = 10

# PostgreSQL with connection pooling
[database.sources.postgres]
type = "postgresql"
host = "localhost"
port = 5432
user = "gromozeka"
password = "password"
database = "gromozeka_db"
pool-size = 10
```

## 🔗 Related Documentation

- **Database Class**: [`internal/database/database.py`](../internal/database/database.py:1)
- **Database Manager**: [`internal/database/manager.py`](../internal/database/manager.py:1)
- **Repository Base Class**: [`internal/database/repositories/base.py`](../internal/database/repositories/base.py:1)
- **Database Models**: [`internal/database/models.py`](../internal/database/models.py:1)
- **Migration Manager**: [`internal/database/migrations/manager.py`](../internal/database/migrations/manager.py:25)
- **Migration Base Class**: [`internal/database/migrations/base.py`](../internal/database/migrations/base.py:7)
- **Chat Settings Keys**: [`internal/bot/models/chat_settings.py`](../internal/bot/models/chat_settings.py:41)

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

- **Total Tables**: 20+ (including dynamic cache tables)
- **Core Tables**: 5 (messages, users, info, topics, settings)
- **Cache Tables**: 7+ (dynamic based on CacheType enum)
- **Spam Detection Tables**: 4 (spam, ham, tokens, classes)
- **Statistics Tables**: 2 (chat stats, user stats)
- **Current Migration Version**: 15
- **Total Repositories**: 12 specialized repositories

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

**Last Updated**: 2026-05-02
**Database Version**: 15
**Documentation Version**: 2.2