# Database Documentation

Welcome to the Gromozeka bot's database documentation, dood! This directory contains comprehensive documentation for the SQLite database schema and operations.

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

### Multi-Source Database Support
The database wrapper supports routing different chats to different SQLite database files:
- **Data isolation**: Separate databases for different chat groups
- **Performance optimization**: Distribute load across multiple files
- **Read-only sources**: Support for read-only database replicas
- **3-tier routing**: Explicit source, chat mapping, or default fallback

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

Learn more: [TypedDict Models](database-schema.md#typeddict-models)

## 🚀 Getting Started

### For Developers

1. **Read the Schema Documentation**: Start with [`database-schema.md`](database-schema.md) to understand the complete database structure
2. **Review the Wrapper Class**: Check [`DatabaseWrapper`](../internal/database/wrapper.py:128) for available methods
3. **Explore TypedDict Models**: See [`internal/database/models.py`](../internal/database/models.py:1) for data structures
4. **Study Migration Examples**: Look at [`internal/database/migrations/versions/`](../internal/database/migrations/versions/) for migration patterns

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

# Save a message
db.saveChatMessage(
    date=datetime.now(),
    chatId=-1001234567890,
    userId=123456789,
    messageId="12345",
    messageText="Hello, world!",
    messageType=MessageType.TEXT,
    messageCategory=MessageCategory.USER
)

# Retrieve recent messages
messages = db.getChatMessagesSince(
    chatId=-1001234567890,
    sinceDateTime=datetime.now() - timedelta(hours=1),
    limit=50
)
```

### Multi-Source Routing
```python
# Explicit source routing
messages = db.getChatMessages(chatId=123, dataSource="archive")

# Chat mapping routing (configured in config.toml)
messages = db.getChatMessages(chatId=-1001234567890)  # Routes to mapped source

# Default routing
messages = db.getChatMessages(chatId=456)  # Routes to default source
```

### Chat Settings Management
```python
# Get all settings for a chat
settings = db.getChatSettings(chatId=-1001234567890)
model = settings.get('chat-model', 'default-model')

# Set a specific setting
db.setChatSetting(
    chatId=-1001234567890,
    key='parse-images',
    value='true'
)
```

## 🔗 Related Documentation

- **Database Wrapper Implementation**: [`internal/database/wrapper.py`](../internal/database/wrapper.py:128)
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
- **Current Migration Version**: 7

## 🤝 Contributing

When modifying the database schema:

1. Create a new migration file with incremented version number
2. Update both documentation files:
   - [`database-schema.md`](database-schema.md) - Full technical details
   - [`database-schema-llm.md`](database-schema-llm.md) - Concise reference
3. Update TypedDict models in [`internal/database/models.py`](../internal/database/models.py:1)
4. Add corresponding methods to [`DatabaseWrapper`](../internal/database/wrapper.py:128)
5. Test migrations on all configured data sources

## 📝 License

This documentation is part of the Gromozeka bot project.

---

**Last Updated**: 2025-12-12  
**Database Version**: 7  
**Documentation Version**: 1.0