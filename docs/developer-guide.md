# Gromozeka Developer Guide

> Hey  Welcome to the Gromozeka developer guide! This doc covers everything you need to understand, maintain, and extend the project Buckle up because there's a LOT to cover

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [Directory Structure](#3-directory-structure)
4. [Configuration System](#4-configuration-system)
5. [Database Layer](#5-database-layer)
6. [Handler System](#6-handler-system)
   - Divination Layout Discovery
7. [Service Layer](#7-service-layer)
8. [Libraries Reference](#8-libraries-reference)
9. [Testing Guide](#9-testing-guide)
10. [Code Quality](#10-code-quality)
11. [Deployment](#11-deployment)
12. [Common Development Tasks](#12-common-development-tasks)

---

## 1. Project Overview

Gromozeka is a production-ready, multi-platform AI bot written in Python 3.12+ It supports two messaging platforms out of the box — Telegram and Max Messenger — while sharing a unified handler pipeline, configuration system, and database layer

### Key Features

- **Multi-platform support** — Telegram and Max Messenger via a common abstraction layer
- **Advanced LLM integration** — Multiple AI provider backends (YandexCloud, OpenRouter, custom OpenAI-compatible) with automatic fallback
- **Service-oriented architecture** — Independent, singleton-pattern services for cache, queue, storage, and LLM
- **Hierarchical TOML configuration** — Layered config system with per-environment, per-chat, and environment-variable overrides
- **ML-powered spam detection** — Naive Bayes filter with auto-learning capability
- **Comprehensive API integrations** — Weather, web search, and geocoding
- **Golden data test framework** — Record/replay pattern for deterministic API testing
- **Migration-based database schema** — Auto-discovered, sequentially versioned SQLite migrations

### Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| Telegram library | `python-telegram-bot` |
| Max Messenger | Custom `lib/max_bot/` client |
| Database | SQLite via `sqlite3` stdlib |
| Configuration | TOML via `tomli` |
| LLM providers | OpenAI-compatible APIs, Yandex Cloud SDK |
| Code style | Black (120 char line length), isort, Flake8, Pyright |
| Testing | pytest with `asyncio_mode = auto` |

### Quick Start

```bash
# 1. Create virtual environment and install deps
make install

# 2. Copy example config and fill in your tokens
cp configs/00-defaults/00-config.toml config.toml
# Edit config.toml with your bot token and API keys

# 3. Run the bot
./venv/bin/python3 main.py --config config.toml
# OR use the run script
./run.sh
```

---

## 2. Architecture Overview

The project is organized in a strict layered architecture where each layer only depends on layers below it

```
┌─────────────────────────────────────────────────────────────────┐
│                          main.py                                │
│                     GromozekBot (orchestrator)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
         ┌───────────────────┴───────────────────┐
         │                                       │
┌────────▼──────────┐               ┌────────────▼──────────┐
│  TelegramBotApp   │               │    MaxBotApplication   │
│ internal/bot/     │               │  internal/bot/max/     │
│  telegram/        │               │                        │
└────────┬──────────┘               └────────────┬──────────┘
         │                                       │
         └───────────────────┬───────────────────┘
                             │
             ┌───────────────▼───────────────┐
             │         HandlersManager        │
             │  internal/bot/common/handlers/ │
             │         manager.py             │
             └───────────────┬───────────────┘
                             │
    ┌────────────────────────┼────────────────────────┐
    │                        │                        │
┌───▼──────────┐   ┌─────────▼──────────┐  ┌─────────▼──────────┐
│ BaseBotHandler│  │   Individual        │  │  ExampleCustom     │
│  base.py      │  │   Handlers          │  │  Handler           │
└───────────────┘  │  (spam, media,      │  └────────────────────┘
                   │   llm_messages, ...) │
                   └────────────────────┘
                             │
         ┌───────────────────┼───────────────────────┐
         │                   │                       │
┌────────▼──────┐  ┌─────────▼──────────┐  ┌────────▼──────────┐
│  CacheService  │  │    QueueService     │  │   StorageService  │
│ internal/      │  │  internal/services/ │  │ internal/services/│
│  services/     │  │  queue_service/     │  │  storage/         │
│  cache/        │  └────────────────────┘  └───────────────────┘
└───────────────┘
         │
┌────────▼──────────────────────────────────────────────────────┐
│                         Database                               │
│                  internal/database/database.py                 │
│         (Multi-source SQL with repositories & migrations)      │
└───────────────────────────────────────────────────────────────┘
         │
┌────────▼──────────────────────────────────────────────────────┐
│                       Libraries (lib/)                         │
│  ai/  cache/  rate_limiter/  max_bot/  openweathermap/        │
│  yandex_search/  geocode_maps/  bayes_filter/  markdown/       │
└───────────────────────────────────────────────────────────────┘
```

### Key Design Patterns

| Pattern | Where Used | Purpose |
|---|---|---|
| Singleton | [`CacheService`](internal/services/cache/service.py:88), [`QueueService`](internal/services/queue_service/service.py), [`RateLimiterManager`](lib/rate_limiter/manager.py:12) | Shared state across handlers |
| Abstract Base Class | [`AbstractModel`](lib/ai/abstract.py:19), [`AbstractLLMProvider`](lib/ai/abstract.py:257), [`CacheInterface`](lib/cache/interface.py:15), [`BaseMigration`](internal/database/migrations/base.py:9) | Type-safe extensibility |
| Chain of Responsibility | Handler pipeline in [`HandlersManager`](internal/bot/common/handlers/manager.py:177) | Sequential/parallel message processing |
| Multi-source Router | [`Database`](internal/database/database.py) | Chat-to-database routing |
| Decorator-based Discovery | `@commandHandlerV2` decorator, [`CommandHandlerMixin`](internal/bot/models) | Auto-discovery of bot commands |
| Golden Data Testing | [`tests/`](tests/) | Deterministic API test replay |

---

## 3. Directory Structure

```
gromozeka/
├── main.py                         # Entry point - GromozekBot orchestrator
├── run.sh                          # Shell script to start the bot
├── Makefile                        # Dev commands (format, lint, test, etc.)
├── pyproject.toml                  # Tool configuration (black, flake8, pyright, pytest, isort)
├── requirements.txt                # Python dependencies
│
├── configs/                        # Hierarchical TOML configuration
│   ├── 00-defaults/                # Base default configs (loaded first)
│   │   ├── 00-config.toml          # Core settings (bot, db, rate limiter, APIs)
│   │   └── bot-defaults.toml       # Per-chat-type and global bot defaults
│   └── common/                     # Common overrides

├── internal/                       # Application-specific internal code
│   ├── bot/                        # Bot layer
│   │   ├── common/                 # Shared bot logic
│   │   │   ├── bot.py              # TheBot - multi-platform bot client
│   │   │   ├── handlers/           # All message handlers
│   │   │   │   ├── base.py         # BaseBotHandler + HandlerResultStatus
│   │   │   │   ├── manager.py      # HandlersManager - handler orchestration
│   │   │   │   ├── spam.py         # Spam detection handler
│   │   │   │   ├── llm_messages.py # LLM message handler (main AI handler)
│   │   │   │   ├── media.py        # Media processing (images, docs, etc.)
│   │   │   │   ├── message_preprocessor.py  # Message saving + pre-processing
│   │   │   │   ├── configure.py    # /configure command handler
│   │   │   │   ├── summarization.py# Chat summarization handler
│   │   │   │   ├── user_data.py    # User data management handler
│   │   │   │   ├── dev_commands.py # Developer/admin command handler
│   │   │   │   ├── weather.py      # Weather integration handler
│   │   │   │   ├── yandex_search.py# Yandex search integration handler
│   │   │   │   ├── topic_manager.py# Telegram topic management handler
│   │   │   │   ├── react_on_user.py# User reaction handler
│   │   │   │   ├── resender.py     # Message forwarding handler
│   │   │   │   ├── common.py       # Common shared handler logic
│   │   │   │   ├── help_command.py # /help command handler
│   │   │   │   ├── module_loader.py# Dynamic custom handler loader
│   │   │   │   ├── example.py      # Example handler (reference)
│   │   │   │   └── example_custom_handler.py  # Example custom handler template
│   │   │   ├── models.py           # Common bot models
│   │   │   └── typing_manager.py   # Typing indicator manager
│   │   ├── telegram/               # Telegram-specific implementation
│   │   │   └── application.py      # TelegramBotApplication
│   │   ├── max/                    # Max Messenger-specific implementation
│   │   │   └── application.py      # MaxBotApplication
│   │   └── models/                 # Shared bot domain models
│   │       ├── enums.py            # BotProvider, ChatType, ChatTier, etc.
│   │       ├── ensured_message.py  # EnsuredMessage - unified message model
│   │       ├── chat_settings.py    # ChatSettingsKey, ChatSettingsValue, etc.
│   │       └── command_handlers.py # CommandHandlerInfo, decorators
│   │
│   ├── config/                     # Configuration management
│   │   └── manager.py              # ConfigManager - hierarchical TOML loader
│   │
│   ├── database/                   # Database layer
│   │   ├── database.py             # Database - main database interface
│   │   ├── manager.py              # DatabaseManager - lifecycle management
│   │   ├── models.py               # TypedDict models for DB rows
│   │   ├── bayes_storage.py        # Bayes filter DB storage
│   │   ├── generic_cache.py        # Generic DB cache storage
│   │   ├── providers/              # Database provider implementations
│   │   │   ├── base.py             # BaseProvider abstract class
│   │   │   ├── sqlite3.py          # SQLite provider
│   │   │   ├── mysql.py            # MySQL provider
│   │   │   ├── postgresql.py       # PostgreSQL provider
│   │   │   └── utils.py            # Provider utilities
│   │   ├── repositories/           # Repository pattern implementations
│   │   │   ├── base.py             # BaseRepository abstract class
│   │   │   ├── cache.py            # Cache repository
│   │   │   ├── chat_info.py        # Chat info repository
│   │   │   ├── chat_messages.py    # Chat messages repository
│   │   │   ├── chat_settings.py    # Chat settings repository
│   │   │   ├── chat_summarization.py # Chat summarization repository
│   │   │   ├── chat_users.py       # Chat users repository
│   │   │   ├── common.py           # Common repository
│   │   │   ├── delayed_tasks.py    # Delayed tasks repository
│   │   │   ├── media_attachments.py # Media attachments repository
│   │   │   ├── spam.py             # Spam repository
│   │   │   └── user_data.py        # User data repository
│   │   └── migrations/             # Migration system
│   │       ├── base.py             # BaseMigration abstract class
│   │       ├── manager.py          # MigrationManager - auto-discovery + apply
│   │       ├── create_migration.py # Script to scaffold new migrations
│   │       └── versions/           # Migration files (migration_001 to migration_016)
│   │
│   ├── services/                   # Service layer (singletons)
│   │   ├── cache/                  # Cache service
│   │   │   ├── service.py          # CacheService singleton
│   │   │   ├── models.py           # CacheNamespace, CachePersistenceLevel
│   │   │   └── types.py            # TypedDicts for cache structures
│   │   ├── llm/                    # LLM service wrapper
│   │   │   └── service.py          # LLMService singleton
│   │   ├── queue_service/          # Async task queue service
│   │   │   ├── service.py          # QueueService singleton
│   │   │   └── types.py            # DelayedTask, DelayedTaskFunction, etc.
│   │   └── storage/                # File storage service (S3/local)
│   │       └── service.py          # StorageService singleton
│   │
│   └── models/                     # Shared internal models
│       └── ...                     # MessageId, MessageType, etc.
│
├── lib/                            # Reusable library components
│   ├── ai/                         # LLM abstraction layer
│   │   ├── abstract.py             # AbstractModel, AbstractLLMProvider
│   │   ├── manager.py              # LLMManager - provider+model registry
│   │   ├── models.py               # ModelMessage, ModelRunResult, etc.
│   │   └── providers/              # Concrete LLM provider implementations
│   │       ├── basic_openai_provider.py
│   │       ├── custom_openai_provider.py
│   │       ├── openrouter_provider.py
│   │       ├── yc_openai_provider.py
│   │       └── yc_sdk_provider.py
│   ├── cache/                      # Generic typed cache library
│   │   ├── interface.py            # CacheInterface[K, V] abstract
│   │   ├── dict_cache.py           # DictCache in-memory implementation
│   │   ├── key_generator.py        # Key generators for cache
│   │   ├── types.py                # TypeVars K, V
│   │   └── value_converter.py      # Value conversion helpers
│   ├── rate_limiter/               # Rate limiting library
│   │   ├── interface.py            # RateLimiterInterface abstract
│   │   ├── manager.py              # RateLimiterManager singleton
│   │   └── sliding_window.py       # SlidingWindowRateLimiter implementation
│   ├── max_bot/                    # Max Messenger client library
│   │   ├── client.py               # MaxBotClient async HTTP client
│   │   ├── constants.py            # API URLs, timeouts, etc.
│   │   ├── exceptions.py           # MaxBotError hierarchy
│   │   ├── utils.py                # Utility helpers
│   │   └── models/                 # Max API model classes (hand-rolled, no pydantic)
│   ├── openweathermap/             # OpenWeatherMap API client
│   │   ├── client.py               # OpenWeatherMapClient
│   │   └── models.py               # WeatherData, GeocodingResult, etc.
│   ├── geocode_maps/               # Geocode Maps API client
│   │   ├── client.py               # GeocodeMapsClient
│   │   └── models.py               # SearchResponse, ReverseResponse, etc.
│   ├── markdown/                   # Custom Markdown parser
│   │   ├── parser.py               # MarkdownParser (main entry point)
│   │   ├── tokenizer.py            # Tokenizer
│   │   ├── block_parser.py         # Block-level parser
│   │   ├── inline_parser.py        # Inline-level parser
│   │   ├── renderer.py             # HTMLRenderer, MarkdownV2Renderer
│   │   └── ast_nodes.py            # AST node types
│   ├── logging_utils.py            # Logging helpers (initLogging)
│   └── utils.py                    # Shared utility functions
│
├── tests/                          # Test suite
│   ├── conftest.py                 # Shared pytest fixtures
│   ├── utils.py                    # Test utilities
│   ├── bot/                        # Bot layer tests
│   ├── fixtures/                   # Golden data fixtures (JSON)
│   ├── geocode_maps/               # Geocode Maps client tests
│   ├── integration/                # Integration tests
│   ├── lib_ai/                     # LLM library tests
│   ├── lib_ratelimiter/            # Rate limiter tests
│   ├── openweathermap/             # Weather client tests
│   ├── services/                   # Service layer tests
│   └── yandex_search/              # Yandex search client tests
│
├── docs/                           # Project documentation
│   └── reports/                    # Development reports and ADRs
```

---

## 4. Configuration System

The configuration system uses hierarchical TOML files Configs are merged in sorted order from all specified directories, with later files overriding earlier ones

### How Config Loading Works

[`ConfigManager`](internal/config/manager.py:59) loads configs in the following priority order (lowest to highest)

1. Config files from `--config-dir` directories (loaded recursively, sorted alphabetically)
2. The single `--config` file (default: `config.toml`)

When files have the same keys, later files override earlier ones. Nested dictionaries are **deep-merged**, not replaced

```bash
# Load from a directory (all .toml files loaded recursively in sorted order)
./venv/bin/python3 main.py --config-dir configs/00-defaults --config-dir configs/common

# Print the merged config and exit
./venv/bin/python3 main.py --config-dir configs/00-defaults --print-config
```

### Environment Variable Substitution

Any value in TOML can reference environment variables using `${VAR_NAME}` syntax

```toml
[bot]
token = "${TELEGRAM_BOT_TOKEN}"

[database.providers.default.parameters]
dbPath = "${DB_PATH}"
```

The `.env` file (default path, configurable with `--dotenv-file`) is loaded before substitution happens

### Config Sections

#### `[application]`

```toml
[application]
root-dir = "storage"   # Change working directory to this path on startup
```

#### `[bot]`

```toml
[bot]
mode = "telegram"                    # "telegram" or "max"
token = "YOUR_BOT_TOKEN_HERE"        # Bot token from @BotFather or Max
bot_owners = ["username", 123456]    # List of usernames/IDs with owner privileges
spam-button-salt = "some_salt"       # Salt for signing spam action buttons
max-tasks = 1024                     # Max concurrent message tasks globally
max-tasks-per-chat = 512             # Max concurrent tasks per chat
```

#### `[bot.defaults]` — Global per-chat defaults

These are the default settings applied to all chats They can be overridden per-chat via the `/configure` command or database

```toml
[bot.defaults]
admin-can-change-settings = true
bot-nicknames = "Громозека, Gro"
llm-message-format = "smart"          # "text", "json", or "smart"
use-tools = true
parse-attachments = true
allow-tools-commands = true
detect-spam = false
bayes-enabled = true
allow-mention = true
allow-reply = true
random-answer-probability = 0.01
chat-model = "openrouter/mistral-7b-instruct:free"
fallback-model = "openrouter/gemma-3-12b-it:free"
summary-model = "openrouter/gemma-3-12b-it:free"
chat-prompt = "You are a helpful assistant..."
```

#### `[bot.private-defaults]`, `[bot.group-defaults]`, `[bot.channel-defaults]`

These override `[bot.defaults]` for specific chat types

```toml
[bot.private-defaults]
random-answer-probability = 1       # Always respond in private chats
detect-spam = false
base-tier = "free-personal"

[bot.group-defaults]
random-answer-probability = 0.01    # Rarely respond randomly in groups

[bot.channel-defaults]
allow-mention = false
allow-reply = false
random-answer-probability = 0
```

#### `[bot.tier-defaults.<tier_name>]`

```toml
[bot.tier-defaults.free]
# Settings for free-tier chats
[bot.tier-defaults.paid]
# Settings for paid-tier chats
```

#### `[database]`

```toml
[database]
default = "default"           # Name of the default provider

[database.providers.default]
provider = "sqlite3"

[database.providers.default.parameters]
dbPath = "bot_data.db"
readOnly = false
timeout = 30
useWal = true
keepConnection = false        # Connect on demand (default for file-based DBs)

# Multi-source: map specific chats to different databases
[database.chatMapping]
"-1001234567890" = "secondary"   # Chat ID string -> provider name
```

**`keepConnection` parameter:**
- `true` — Connect immediately when provider is created (good for readonly replicas, in-memory DBs)
- `false` — Connect on first query (default for file-based DBs, saves resources)
- `null` — Auto-detect: `true` for in-memory SQLite3, `false` otherwise
- **Special case:** In-memory SQLite3 (`:memory:`) defaults to `true` to prevent data loss

#### `[ratelimiter]`

```toml
[ratelimiter.ratelimiters.default]
type = "SlidingWindow"
[ratelimiter.ratelimiters.default.config]
windowSeconds = 5
maxRequests = 5

[ratelimiter.ratelimiters.one-per-second]
type = "SlidingWindow"
[ratelimiter.ratelimiters.one-per-second.config]
windowSeconds = 1
maxRequests = 1

[ratelimiter.queues]
yandex-search = "default"
openweathermap = "default"
geocode-maps = "one-per-second"
chat-default = "default"
```

#### `[models]`

```toml
[models.providers.openrouter]
type = "openrouter"
api-key = "${OPENROUTER_API_KEY}"

[models.providers.yandex]
type = "yc-openai"
api-key = "${YC_API_KEY}"
folder-id = "${YC_FOLDER_ID}"

[models.models.my-model]
provider = "openrouter"
model_id = "mistralai/mistral-7b-instruct"
temperature = 0.7
context = 32768
enabled = true
# Capability flags
support_images = false
support_tools = true
# Tier access
tier = "free"     # "free", "paid", "bot_owner"
```

#### `[logging]`

```toml
[logging]
level = "INFO"
format = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
console = true
file = "logs/gromozeka.log"
error-file = "logs/gromozeka.err.log"
rotate = true
```

### `ConfigManager` API

```python
from internal.config.manager import ConfigManager

configManager = ConfigManager(
    configPath="config.toml",
    configDirs=["configs/00-defaults"],
    dotEnvFile=".env",
)

botConfig = configManager.getBotConfig()
dbConfig = configManager.getDatabaseConfig()
modelsConfig = configManager.getModelsConfig()
loggingConfig = configManager.getLoggingConfig()
rateLimiterConfig = configManager.getRateLimiterConfig()
weatherConfig = configManager.getOpenWeatherMapConfig()
yandexConfig = configManager.getYandexSearchConfig()
```

---

## 5. Database Layer

The database layer provides SQL access via [`Database`](internal/database/database.py) with multi-source routing, connection pooling, repository pattern, and an automatic migration system It supports SQLite, MySQL, and PostgreSQL through a provider abstraction

### Database

[`Database`](internal/database/database.py) is the main interface to the database It supports multiple named database providers, with per-chat routing so different chats can use different databases The database uses a repository pattern with 12 specialized repositories for different data domains

```python
from internal.database import Database

db = Database(config={
    "default": "default",
    "providers": {
        "default": {
            "provider": "sqlite3",
            "parameters": {
                "dbPath": "bot_data.db",
                "readOnly": False,
                "timeout": 30,
            },
        }
    },
    # Optional: route specific chats to other providers
    "chatMapping": {
        "-1001234567890": "secondary",
    }
})
```

### Repository Pattern

The database layer uses a repository pattern with 12 specialized repositories Each repository handles a specific data domain and provides type-safe methods for data access

| Repository | File | Purpose |
|---|---|---|
| [`CacheRepository`](internal/database/repositories/cache.py) | `cache.py` | Cache storage operations |
| [`ChatInfoRepository`](internal/database/repositories/chat_info.py) | `chat_info.py` | Chat metadata operations |
| [`ChatMessagesRepository`](internal/database/repositories/chat_messages.py) | `chat_messages.py` | Message history operations |
| [`ChatSettingsRepository`](internal/database/repositories/chat_settings.py) | `chat_settings.py` | Chat settings operations |
| [`ChatSummarizationRepository`](internal/database/repositories/chat_summarization.py) | `chat_summarization.py` | Chat summarization operations |
| [`ChatUsersRepository`](internal/database/repositories/chat_users.py) | `chat_users.py` | Per-chat user metadata operations |
| [`CommonRepository`](internal/database/repositories/common.py) | `common.py` | Common database operations |
| [`DelayedTasksRepository`](internal/database/repositories/delayed_tasks.py) | `delayed_tasks.py` | Background task queue operations |
| [`DivinationRepository`](internal/database/repositories/divinations.py) | `divinations.py` | Tarot/runes readings and layout discovery operations |
| [`MediaAttachmentsRepository`](internal/database/repositories/media_attachments.py) | `media_attachments.py` | Media metadata operations |
| [`SpamRepository`](internal/database/repositories/spam.py) | `spam.py` | Spam detection operations |
| [`UserDataRepository`](internal/database/repositories/user_data.py) | `user_data.py` | User data operations |

### Multi-Source Routing

When you call most database methods with a `chatId`, the database automatically selects the right source If a chat isn't in the `chatMapping`, it falls back to the `default` source

```python
# Routes to the source mapped for chatId (-1001234567890 -> "secondary")
settings = db.getChatSettings(chatId=-1001234567890)

# Explicitly pass dataSource to override routing
messages = db.getChatMessages(chatId=123, dataSource="archive")
```

### SQL Portability

The database layer supports multiple SQL backends through a provider abstraction SQL portability is fully implemented, supporting SQLite, MySQL, and PostgreSQL

| Provider | Type | Config Key |
|---|---|---|
| SQLite | `sqlite3` | Built-in, uses `sqlite3` stdlib |
| MySQL | `mysql` | Requires `mysql-connector-python` |
| PostgreSQL | `postgresql` | Requires `psycopg2-binary` |

**Important**: Migration 013 removed `DEFAULT CURRENT_TIMESTAMP` for cross-database compatibility All timestamp columns now use explicit values in application code

### Connection Management

Database providers support configurable connection management via the `keepConnection` parameter

**`keepConnection` parameter values:**
- `true` — Connect immediately when provider is created (good for readonly replicas, in-memory DBs)
- `false` — Connect on first query (default for file-based DBs, saves resources)
- `null` — Auto-detect: `true` for in-memory SQLite3, `false` otherwise

**Special case:** In-memory SQLite3 (`:memory:`) defaults to `true` to prevent data loss

**Configuration example:**
```toml
[database.providers.default.parameters]
keepConnection = false  # Connect on demand (default for file-based DBs)

[database.providers.readonly.parameters]
keepConnection = true  # Connect immediately (good for readonly replicas)
```

**Migration connection management:** Migrations rely on the provider's `keepConnection` parameter for connection management No explicit `await sqlProvider.connect()` call is made during migration

### Database Schema (15+ Tables)

The schema is defined and evolved through migrations. Key tables include:

| Table | Purpose |
|---|---|
| `chats` | Chat metadata (id, type, title, etc.) |
| `chat_settings` | Per-chat key-value bot settings |
| `chat_users` | Per-chat user metadata, join counts, message counts |
| `chat_messages` | Message history for LLM context |
| `spam_messages` | Detected spam messages |
| `cache` | General-purpose persistent cache |
| `cache_storage` | Extended cache storage |
| `media_attachments` | Uploaded media metadata |
| `delayed_tasks` | Background task queue persistence |
| `summarization_cache` | Chat summarization results |
| `bayes_filter` | Bayes filter training data |

### Migration System

Migrations live in [`internal/database/migrations/versions/`](internal/database/migrations/versions/) and are auto-discovered by [`MigrationManager`](internal/database/migrations/manager.py)

Each migration inherits from [`BaseMigration`](internal/database/migrations/base.py:9):

```python
from internal.database.migrations.base import BaseMigration
from internal.database.providers import BaseSQLProvider

class Migration(BaseMigration):
    version = 13          # Must be unique sequential integer!
    description = "Add my_new_table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        await sqlProvider.execute("""
            CREATE TABLE IF NOT EXISTS my_new_table (
                chat_id INTEGER PRIMARY KEY NOT NULL,
                value TEXT,
                created_at TIMESTAMP NOT NULL
            )
        """)

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        await sqlProvider.execute("DROP TABLE IF EXISTS my_new_table")
```

Migrations are applied automatically on [`Database`](internal/database/database.py) initialization The schema version is tracked in a `schema_migrations` table.

### How to Add a Migration

1. **Check the latest migration version** first

```bash
ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
```

2. **Create the migration file** using the next sequential number:

```bash
# If latest is migration_012, create migration_013
cp internal/database/migrations/versions/migration_012_unify_cache_tables.py \
   internal/database/migrations/versions/migration_013_my_change.py
```

3. **Edit the file** to set `version`, `description`, and implement `up()` / `down()`

4. **Register the migration** in [`internal/database/migrations/versions/__init__.py`](internal/database/migrations/versions/__init__.py) if needed.

5. **Run the bot** — migrations are applied automatically

> ⚠️ **NEVER reuse or skip version numbers!** The version number is immutable once deployed

---

## 6. Handler System

The handler system is the core of message processing All incoming messages go through a pipeline of handlers managed by [`HandlersManager`](internal/bot/common/handlers/manager.py:177)

### Handler Lifecycle

```
1. HandlersManager.__init__() is called during bot startup
2. Built-in handlers are registered in order:
   - MessagePreprocessorHandler (always SEQUENTIAL, first)
   - SpamHandler (always SEQUENTIAL, second)
   - ConfigureCommandHandler, SummarizationHandler, UserDataHandler,
     DevCommandsHandler, MediaHandler, CommonHandler, HelpHandler
   - Platform-specific handlers (Telegram-only)
   - Config-gated handlers: DivinationHandler (if divination.enabled),
     WeatherHandler, YandexSearchHandler, ResenderHandler
   - Custom handlers via CustomHandlerLoader.loadAll() (if custom-handlers.enabled)
3. LLMMessageHandler is registered last (always SEQUENTIAL)
4. Messages flow through handlers in the specified order
```
Incoming Message
       │
       ▼
  HandlersManager.handleMessage()
       │
       ▼
  [MessagePreprocessorHandler] ← SEQUENTIAL (always runs first)
       │ saves message to DB, preprocesses text
       ▼
  [SpamHandler] ← SEQUENTIAL (runs second)
       │ checks for spam, may block further processing
       ▼
   [All other handlers] ← PARALLEL (run concurrently)
        │
        ├── ConfigureCommandHandler
        ├── SummarizationHandler
        ├── UserDataHandler
        ├── DevCommandsHandler
        ├── MediaHandler
        ├── CommonHandler
        ├── HelpHandler
        ├── ReactOnUserMessageHandler (Telegram only)
        ├── TopicManagerHandler (Telegram only)
        ├── DivinationHandler (if enabled)
        ├── WeatherHandler (if enabled)
        ├── YandexSearchHandler (if enabled)
        ├── ResenderHandler (if enabled)
        ├── [custom handlers via CustomHandlerLoader]
        │
        ▼
   [LLMMessageHandler] ← SEQUENTIAL (always runs last)
```

### HandlerResultStatus

Each handler returns a [`HandlerResultStatus`](internal/bot/common/handlers/base.py:82) to signal how processing should continue

```python
class HandlerResultStatus(Enum):
    FINAL = "final"    # Handled, stop processing (e.g., spam deleted)
    SKIPPED = "skipped" # Not applicable, continue to next handler
    NEXT = "next"      # Processed but continue to next handler
    ERROR = "error"    # Error occurred, but continue anyway
    FATAL = "fatal"    # Fatal error, stop all processing immediately
```

### HandlerParallelism

```python
class HandlerParallelism(IntEnum):
    SEQUENTIAL = auto()  # Run one at a time, wait for result
    PARALLEL = auto()    # Run concurrently with other PARALLEL handlers
```

### BaseBotHandler

All handlers inherit from [`BaseBotHandler`](internal/bot/common/handlers/base.py:110) This base class provides:

- `self.db` — [`Database`](internal/database/database.py) instance
- `self.llmService` — [`LLMService`](internal/services/llm/service.py) instance (access LLMManager via `self.llmService.getLLMManager()`)
- `self.cache` — [`CacheService`](internal/services/cache/service.py:88) instance
- `self.queueService` — [`QueueService`](internal/services/queue_service/service.py) instance
- `self.storage` — [`StorageService`](internal/services/storage/service.py) instance
- `self.configManager` — [`ConfigManager`](internal/config/manager.py:59) instance
- `self.config` — raw bot config dict
- `self.botProvider` — [`BotProvider`](internal/bot/models/enums.py) enum

Key methods from [`BaseBotHandler`](internal/bot/common/handlers/base.py:110):

```python
# Get merged chat settings (with defaults)
settings = self.getChatSettings(chatId=123)

# Send a message back to the user
await self.sendMessage(ensuredMessage, messageText="Hello")

# Check if user is a bot admin
isAdmin = await self.isAdmin(ensuredMessage)

# Check if user is a bot owner
isOwner = self.isBotOwner(ensuredMessage.sender)

# Process media with LLM
mediaInfo = await self._processMediaV2(ensuredMessage, prompt="Describe this")
```

### Command Handler Decorator

Use the `@commandHandlerV2` decorator to register a method as a bot command handler

```python
from internal.bot.models import (
    commandHandlerV2,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
)

@commandHandlerV2(
    commands=("mycommand", "mc"),           # Command names (with or without /)
    shortDescription="- short description",  # Shown in /help list
    helpMessage="Full help text for this command",
    visibility={CommandPermission.DEFAULT},   # Who sees it in /help
    availableFor={CommandPermission.DEFAULT}, # Who can use it
    helpOrder=CommandHandlerOrder.NORMAL,
    category=CommandCategory.TOOLS,
)
async def myCommandHandler(
    self,
    ensuredMessage: EnsuredMessage,
    command: str,
    args: str,
    updateObj: UpdateObjectType,
    typingManager: Optional[TypingManager],
) -> None:
    await self.sendMessage(ensuredMessage, messageText="Command result")
```

### Available Handler List

| Handler | File | Description |
|---|---|---|
| `MessagePreprocessorHandler` | [`message_preprocessor.py`](internal/bot/common/handlers/message_preprocessor.py) | Save message to DB, preprocess text |
| `SpamHandler` | [`spam.py`](internal/bot/common/handlers/spam.py) | ML spam detection + user management |
| `ConfigureCommandHandler` | [`configure.py`](internal/bot/common/handlers/configure.py) | `/configure` settings wizard |
| `SummarizationHandler` | [`summarization.py`](internal/bot/common/handlers/summarization.py) | `/summarize` chat history |
| `UserDataHandler` | [`user_data.py`](internal/bot/common/handlers/user_data.py) | User profile management |
| `DevCommandsHandler` | [`dev_commands.py`](internal/bot/common/handlers/dev_commands.py) | Developer/admin commands |
| `MediaHandler` | [`media.py`](internal/bot/common/handlers/media.py) | Image/file/sticker processing |
| `CommonHandler` | [`common.py`](internal/bot/common/handlers/common.py) | Shared command handling |
| `HelpHandler` | [`help_command.py`](internal/bot/common/handlers/help_command.py) | `/help` command |
| `ReactOnUserMessageHandler` | [`react_on_user.py`](internal/bot/common/handlers/react_on_user.py) | User join/leave reactions |
| `TopicManagerHandler` | [`topic_manager.py`](internal/bot/common/handlers/topic_manager.py) | Forum topic management |
| `DivinationHandler` | [`divination.py`](internal/bot/common/handlers/divination.py) | `/taro` and `/runes` divination commands |
| `WeatherHandler` | [`weather.py`](internal/bot/common/handlers/weather.py) | Weather query handler |
| `YandexSearchHandler` | [`yandex_search.py`](internal/bot/common/handlers/yandex_search.py) | Web search handler |
| `ResenderHandler` | [`resender.py`](internal/bot/common/handlers/resender.py) | Message forwarding |
| `LLMMessageHandler` | [`llm_messages.py`](internal/bot/common/handlers/llm_messages.py) | Main AI conversation handler |

### How to Create a New Handler

See [`example_custom_handler.py`](internal/bot/common/handlers/example_custom_handler.py) for a complete working example

**Step 1**: Create your handler class in a new file

```python
# internal/bot/common/handlers/my_handler.py
"""My new handler module"""

import logging
from typing import Optional

from internal.bot.common.models import UpdateObjectType
from internal.bot.common.typing_manager import TypingManager
from internal.bot.models import (
    BotProvider,
    CommandCategory,
    CommandHandlerOrder,
    CommandPermission,
    EnsuredMessage,
    commandHandlerV2,
)
from internal.config.manager import ConfigManager
from internal.database.models import MessageCategory
from internal.database import Database

from .base import BaseBotHandler, HandlerResultStatus

logger = logging.getLogger(__name__)


class MyNewHandler(BaseBotHandler):
    """My new handler that does cool things"""

    def __init__(
        self,
        *,
        configManager: ConfigManager,
        database: Database,
        botProvider: BotProvider,
    ):
        """Initialize my handler"""
        super().__init__(
            configManager=configManager,
            database=database,
            botProvider=botProvider,
        )

    async def newMessageHandler(
        self, ensuredMessage: EnsuredMessage, updateObj: UpdateObjectType
    ) -> HandlerResultStatus:
        """Process incoming messages"""
        # Return SKIPPED if this handler doesn't apply to this message
        if not self._shouldHandle(ensuredMessage):
            return HandlerResultStatus.SKIPPED

        # Do your work here...
        await self.sendMessage(ensuredMessage, messageText="I handled it")
        return HandlerResultStatus.FINAL  # Stop further processing

    def _shouldHandle(self, ensuredMessage: EnsuredMessage) -> bool:
        """Check if this handler applies to the message"""
        return True  # Handle everything for now

    @commandHandlerV2(
        commands=("mycmd",),
        shortDescription="- my command",
        helpMessage="Does something cool",
        visibility={CommandPermission.DEFAULT},
        availableFor={CommandPermission.DEFAULT},
        helpOrder=CommandHandlerOrder.NORMAL,
        category=CommandCategory.TOOLS,
    )
    async def myCommand(
        self,
        ensuredMessage: EnsuredMessage,
        command: str,
        args: str,
        updateObj: UpdateObjectType,
        typingManager: Optional[TypingManager],
    ) -> None:
        """Handle /mycmd command"""
        await self.sendMessage(
            ensuredMessage,
            messageText="My command result",
            messageCategory=MessageCategory.BOT_COMMAND_REPLY,
        )
```

**Step 2**: Register the handler in [`HandlersManager`](internal/bot/common/handlers/manager.py:249)

```python
# In internal/bot/common/handlers/manager.py, add import:
from .my_handler import MyNewHandler

# Then add to self.handlers list in __init__:
(MyNewHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.PARALLEL),
```

**Alternatively**, use the **custom handler loader** for out-of-tree handlers Configure in TOML:

```toml
[custom-handlers]
enabled = true

[[custom-handlers.handlers]]
id = "my-handler"
module = "path.to.my_handler"
class = "MyNewHandler"
parallelism = "parallel"
order = 10
enabled = true
```

See [`custom-modules-design.md`](../../custom-modules-design.md) for the complete custom handler loading system documentation.

### 6.1 Divination Layout Discovery

The divination handler includes a layout discovery feature that can automatically find and learn new tarot/runes layouts using LLM with web search capability This allows users to request layouts that aren't predefined in the system

#### Enabling Discovery

Enable discovery in your config with the `discovery-enabled` setting

```toml
[divination]
discovery-enabled = true
```

When enabled, unknown layouts in `/taro` or `/runes` commands trigger an automatic discovery process instead of returning an error

#### Discovery Process

The layout discovery follows a 4-step process

**Step 1 - Cache Check**: The handler first checks if the requested layout is already cached in the database (from a previous discovery attempt)

**Step 2 - LLM Discovery (Web Search)**: If not cached, the handler calls `LLMService.generateText(tools=True)` with web search enabled

- The LLM automatically uses the web_search tool to find information about the layout
- Returns a detailed description of the layout including card positions, meanings, and interpretation guidelines
- Uses the `divination-discovery-info-prompt` and `divination-discovery-system-prompt` settings

**Step 3 - LLM Structuring**: The handler then calls `LLMService.generateStructured()` to parse the description into a structured format

- Passes the description and an expected JSON schema
- Returns a validated dictionary with the layout structure
- Uses the `divination-discovery-structure-prompt` setting

**Step 4 - Validation & Save**: The handler validates the structured dictionary and saves it to the database

- On success: Saves the complete layout definition for future reuse
- On failure: Saves a negative cache entry to prevent repeated failed attempts for 24 hours

#### Customizing Discovery Prompts

You can customize the discovery process by editing the discovery prompts in chat settings These can be configured globally in `configs/00-defaults/bot-defaults.toml` or per-chat via the `/configure` command

```toml
[bot.defaults]
# System instruction for both discovery LLM calls
divination-discovery-system-prompt = "You are an expert tarot researcher..."

# Prompt for the first LLM call (with web search enabled)
divination-discovery-info-prompt = "Find complete information about the 'Celtic Cross' tarot reading layout..."

# Prompt for the second LLM call (structured output)
divination-discovery-structure-prompt = "Parse this description into a structured layout JSON..."
```

The system prompt applies to both LLM calls, while the info and structure prompts are specific to each step

#### Testing Discovery

The discovery feature has comprehensive test coverage in:
- [`tests/bot/test_divination_discovery.py`](tests/bot/test_divination_discovery.py) — Full discovery workflow tests

Tests cover:
- Successful layout discovery with valid web search results
- Failed discovery with invalid/unrecognized layouts
- Cache hit scenarios (reusing previously discovered layouts)
- Negative cache (preventing repeated failures)
- Prompt customization and validation

#### Layout Database Table

Discovered layouts are stored in the `divination_layouts` table (added by migration 015)

```toml
[divination.layouts.celtic-cross]
name = "Celtic Cross"
description = "A classic 10-card spread for detailed readings..."
positions = ["Significator", "Situation", "Challenge", ...]
```

---

## 7. Service Layer

The service layer provides singleton services shared across all handlers Services use the `getInstance()` pattern and must be initialized before use

### CacheService

[`CacheService`](internal/services/cache/service.py:88) is a bot-level singleton providing fast in-memory caching with optional database persistence and LRU eviction

```python
from internal.services.cache import CacheService

# Get the singleton (always the same instance)
cache = CacheService.getInstance()

# Must be initialized with database before use
cache.injectDatabase(db)

# Chat settings (most common use case)
settings = cache.getChatSettings(chatId=123)
cache.setChatSettings(chatId=123, key=ChatSettingsKey.CHAT_MODEL, value="my-model")

# User data
cache.setUserData(chatId=123, userId=456, key="points", value=100)
userData = cache.getUserData(chatId=123, userId=456)

# Chat user info
chatUserInfo = cache.getChatUser(chatId=123, userId=456)
```

**Cache Namespaces:**

| Namespace | Key Type | Purpose |
|---|---|---|
| `CHATS` | `int` (chatId) | Chat settings + runtime cache |
| `CHAT_PERSISTENT` | `int` (chatId) | Persistent chat data |
| `CHAT_USERS` | `str` (chatId:userId) | Per-user per-chat data |
| `USERS` | `int` (userId) | Global user data |

### QueueService

[`QueueService`](internal/services/queue_service/service.py) manages background async tasks with delay support It also handles lifecycle events (`DO_EXIT`, `CRON_JOB`)

```python
from internal.services.queue_service import QueueService, makeEmptyAsyncTask

queueService = QueueService.getInstance()

# Register lifecycle handler
async def onExit(task):
    # Cleanup on shutdown
    pass

queueService.registerDelayedTaskHandler(DelayedTaskFunction.DO_EXIT, onExit)

# Enqueue a delayed task
await queueService.enqueue(
    myAsyncFunction,
    delay=5.0,    # Delay in seconds
    args=(arg1, arg2),
)
```

### LLMService

[`LLMService`](internal/services/llm/service.py) wraps [`LLMManager`](lib/ai/manager.py:17) as a singleton service

```python
from internal.services.llm import LLMService

llmService = LLMService.getInstance()
llmService.injectLLMManager(llmManager)

model = llmService.getModel("my-model-name")
```

### StorageService

[`StorageService`](internal/services/storage/service.py) provides file storage (local filesystem or S3-compatible)

```python
from internal.services.storage import StorageService

storage = StorageService.getInstance()
storage.injectConfig(configManager)

# Upload a file
url = await storage.upload(fileBytes, fileName="image.jpg", contentType="image/jpeg")

# Download a file
fileBytes = await storage.download(url)
```

---

## 8. Libraries Reference

### 8.1 AI/LLM System (`lib/ai/`)

The AI system provides a provider-agnostic interface for interacting with multiple LLM backends

**Key classes:**

| Class | File | Description |
|---|---|---|
| [`LLMManager`](lib/ai/manager.py:17) | `manager.py` | Top-level registry of providers and models |
| [`AbstractLLMProvider`](lib/ai/abstract.py:257) | `abstract.py` | Base class for providers |
| [`AbstractModel`](lib/ai/abstract.py:19) | `abstract.py` | Base class for individual models |
| `CustomOpenAIProvider` | `providers/custom_openai_provider.py` | OpenAI-compatible API provider |
| `OpenrouterProvider` | `providers/openrouter_provider.py` | OpenRouter.ai provider |
| `YcOpenaiProvider` | `providers/yc_openai_provider.py` | Yandex Cloud OpenAI-compatible |
| `YcAIProvider` | `providers/yc_sdk_provider.py` | Yandex Cloud native SDK (supports structured output, tool calling, multiple auth methods) |

**Usage example:**

```python
from lib.ai.manager import LLMManager
from lib.ai import ModelMessage, ModelResultStatus
from internal.services.llm import LLMService

llmManager = LLMManager(config={
    "providers": {
        "openrouter": {
            "type": "openrouter",
            "api-key": "sk-or-...",
        }
    },
    "models": {
        "my-model": {
            "provider": "openrouter",
            "model_id": "mistralai/mistral-7b-instruct",
            "temperature": 0.7,
            "context": 32768,
        }
    }
})

# After creating LLMManager, inject it into LLMService so handlers can access it:
LLMService.getInstance().injectLLMManager(llmManager)

model = llmManager.getModel("my-model")
messages = [
    ModelMessage(role="system", content="You are helpful"),
    ModelMessage(role="user", content="Hello!"),
]
result = await model.generateText(messages)

if result.status == ModelResultStatus.SUCCESS:
    print(result.resultText)
```

**Adding a new LLM provider:**

1. Create `lib/ai/providers/my_provider.py` implementing [`AbstractLLMProvider`](lib/ai/abstract.py:257) and the model class extending [`AbstractModel`](lib/ai/abstract.py:19)
2. Register it in [`LLMManager._initProviders()`](lib/ai/manager.py:36) by adding it to `providerTypes`:

```python
providerTypes = {
    "yc-openai": YcOpenaiProvider,
    "openrouter": OpenrouterProvider,
    "my-provider": MyProvider,   # Add here
    ...
}
```

3. Configure in TOML:

```toml
[models.providers.my-provider]
type = "my-provider"
api-key = "${MY_PROVIDER_API_KEY}"
```

### 8.2 Cache System (`lib/cache/`)

A generic, type-safe cache library for any key-value storage need Not to be confused with `CacheService` (which is bot-specific), this is a general-purpose cache

**Key classes:**

| Class | File | Description |
|---|---|---|
| [`CacheInterface[K, V]`](lib/cache/interface.py:15) | `interface.py` | Abstract base for all caches |
| `DictCache[K, V]` | `dict_cache.py` | In-memory dict-backed cache |
| `NullCache` | *(imported from lib.cache)* | No-op cache (caching disabled) |

**Usage example:**

```python
from lib.cache import DictCache
from lib.cache.key_generator import StringKeyGenerator

# Create a typed cache
cache: CacheInterface[str, dict] = DictCache[str, dict](
    keyGenerator=StringKeyGenerator(),
    defaultTtl=3600,    # 1 hour TTL
    maxSize=500,
)

# Store value
await cache.set("user:123", {"name": "Prinny", "level": 99})

# Retrieve value (None if expired or missing)
userData = await cache.get("user:123")

# Override TTL for specific get
userData = await cache.get("user:123", ttl=600)

# Get stats
stats = cache.getStats()
print(f"Entries: {stats['entries']}, Max: {stats['maxSize']}")

# Clear all
await cache.clear()
```

### 8.3 Rate Limiter (`lib/rate_limiter/`)

Sliding window rate limiter with a global singleton manager Used to limit API call rates for external services

**Key classes:**

| Class | File | Description |
|---|---|---|
| [`RateLimiterManager`](lib/rate_limiter/manager.py:12) | `manager.py` | Singleton manager of named limiters |
| `SlidingWindowRateLimiter` | `sliding_window.py` | Sliding window implementation |
| `RateLimiterInterface` | `interface.py` | Abstract base class |

**Usage example:**

```python
from lib.rate_limiter import RateLimiterManager

# Get singleton
manager = RateLimiterManager.getInstance()

# Apply rate limit before making an API call (will sleep/wait if needed)
await manager.applyLimit("openweathermap")

# Get stats
stats = manager.getStats("openweathermap")
print(f"Requests in window: {stats['requestsInWindow']}/{stats['maxRequests']}")

# Queue-to-limiter bindings are configured via TOML [ratelimiter] section
```

### 8.4 Max Bot Client (`lib/max_bot/`)

An async HTTP client for the Max Messenger Bot API Analogous to `python-telegram-bot` but for Max Messenger

**Key classes:**

| Class | File | Description |
|---|---|---|
| [`MaxBotClient`](lib/max_bot/client.py:75) | `client.py` | Main async client |
| `MaxBotError` | `exceptions.py` | Base exception class |
| `AuthenticationError` | `exceptions.py` | Auth failures |
| `RateLimitError` | `exceptions.py` | Rate limit hit |
| `AttachmentNotReadyError` | `exceptions.py` | Media not ready yet |

**Usage example:**

```python
from lib.max_bot import MaxBotClient

client = MaxBotClient(token="your-max-bot-token")

# Send a message
result = await client.sendMessage(
    chatId=123456,
    text="Hello from Gromozeka",
)

# Get bot info
botInfo = await client.getBotInfo()

# Get chat members
members = await client.getChatMembers(chatId=123456)

# Upload and send a photo
uploadResult = await client.uploadPhoto(photoBytes)
await client.sendMessage(
    chatId=123456,
    text="Look at this",
    attachments=[uploadResult.asAttachment()],
)
```

**Constants** from [`lib/max_bot/constants.py`](lib/max_bot/constants.py):

```python
API_BASE_URL = "https://botapi.max.ru/"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 1.0
```

### 8.5 OpenWeatherMap Client (`lib/openweathermap/`)

Async client for the OpenWeatherMap One Call API 3.0 with integrated caching and rate limiting

```python
from lib.openweathermap import OpenWeatherMapClient
from lib.cache import DictCache

weatherCache = DictCache(defaultTtl=3600)        # 1 hour
geocodingCache = DictCache(defaultTtl=2592000)   # 30 days

client = OpenWeatherMapClient(
    apiKey="your-api-key",
    weatherCache=weatherCache,
    geocodingCache=geocodingCache,
    requestTimeout=10,
    defaultLanguage="ru",
    rateLimiterQueue="openweathermap",   # Must match a ratelimiter queue name
)

# Get coordinates for a city
location = await client.getCoordinates("Moscow", "RU")

# Get current weather by coordinates
weather = await client.getWeather(lat=55.7558, lon=37.6173)

# Combined: city name -> weather (with geocoding cache)
result = await client.getWeatherByCity("Moscow", "RU")
print(f"Temperature: {result.current.temp}°C")
print(f"Description: {result.current.weather[0].description}")
```

### 8.6 Yandex Search Client

Provides web search via Yandex Search API. Configured with `[yandex-search]` in TOML. Used by `YandexSearchHandler`

### 8.7 Geocode Maps Client (`lib/geocode_maps/`)

Async client for the Geocode Maps API (geocode.maps.co) with forward/reverse geocoding and OSM lookup

```python
from lib.geocode_maps import GeocodeMapsClient
from lib.cache import DictCache

client = GeocodeMapsClient(
    apiKey="your-api-key",
    searchCache=DictCache(defaultTtl=2592000),
    reverseCache=DictCache(defaultTtl=2592000),
    lookupCache=DictCache(defaultTtl=2592000),
    acceptLanguage="ru",
    rateLimiterQueue="geocode-maps",
)

# Forward geocoding (address -> coordinates)
results = await client.search("Angarsk, Russia")
if results:
    print(f"Lat: {results[0].lat}, Lon: {results[0].lon}")

# Reverse geocoding (coordinates -> address)
location = await client.reverse(lat=52.5443, lon=103.8882)

# OSM ID lookup
places = await client.lookup(["R2623018"])
```

### 8.8 Bayes Filter (Spam Detection)

The Naive Bayes spam filter lives in the database layer at [`internal/database/bayes_storage.py`](internal/database/bayes_storage.py) and is used by `SpamHandler`

**How it works:**
1. Every message is scored against the trained Bayes model
2. If the spam score exceeds `spam-ban-treshold` (default: 90), the user is banned and messages deleted
3. If it exceeds `spam-warn-treshold` (default: 60), a warning is added
4. New users (fewer than `auto-spam-max-messages` messages) are always checked
5. The filter auto-learns from confirmed spam/ham decisions

**Relevant config keys in `[bot.defaults]`:**

```toml
detect-spam = true
bayes-enabled = true
bayes-auto-learn = true
bayes-min-confidence = 0.5
bayes-use-trigrams = false
bayes-min-confedence-to-autolearn-spam = 0.6
bayes-min-confedence-to-autolearn-ham = 0.9
spam-ban-treshold = 90
spam-warn-treshold = 60
auto-spam-max-messages = 10
spam-delete-all-user-messages = true
```

### 8.9 Markdown Parser (`lib/markdown/`)

A custom Markdown parser that converts standard Markdown to Telegram's MarkdownV2 format (and optionally HTML) This is necessary because Telegram MarkdownV2 has many edge cases that LLM outputs often violate

**Pipeline stages:**

1. `Tokenizer` — splits input into tokens
2. `BlockParser` — identifies block-level elements (headers, lists, code blocks)
3. `InlineParser` — processes inline elements (bold, italic, links)
4. `Renderer` — converts the AST to target format

**Usage:**

```python
from lib.markdown.parser import markdownToMarkdownV2, MarkdownParser

# Quick conversion for bot messages (most common use case)
mdv2Text = markdownToMarkdownV2("**Hello** from _Gromozeka_")

# More control with the parser directly
parser = MarkdownParser(options={
    "preserve_soft_line_breaks": False,
    "ignore_indented_code_blocks": True,
})
mdv2 = parser.toMarkdownV2("# Header\n\n**Bold** text")
html = parser.toHTML("# Header\n\n**Bold** text")
```

---

## 9. Testing Guide

The test suite has 1185+ tests covering all layers of the application Tests use pytest with `asyncio_mode = auto` so async tests work natively

### Running Tests

```bash
# Run all tests (recommended)
make test

# Run all tests with verbose output
make test V=1

# Re-run only previously failed tests
make test-failed

# Run with coverage report
make coverage
# HTML report at: htmlcov/index.html

# Run specific test file
./venv/bin/python3 -m pytest tests/test_db_wrapper.py -v

# Run specific test function
./venv/bin/python3 -m pytest tests/test_db_wrapper.py::test_my_function -v

# Run only slow tests
./venv/bin/python3 -m pytest -m slow

# Exclude slow tests
./venv/bin/python3 -m pytest -m "not slow"
```

### Test Structure

Test files are discovered from three paths (configured in [`pyproject.toml`](pyproject.toml:57)):
- `tests/` — main test suite
- `lib/` — library-level unit tests
- `internal/` — internal module unit tests

Test files must match `test_*.py` or `*_test.py` Test classes must start with `Test`, and test functions with `test_`

### Golden Data Framework

For API client tests (weather, geocoding, search), the project uses a **golden data** (record/replay) pattern This avoids hitting real API endpoints during test runs while maintaining realistic test data

**How it works:**

1. **Record mode**: Tests are run with real API calls, and responses are saved as JSON fixtures in `tests/fixtures/`
2. **Replay mode**: Tests load the fixture files instead of making real API calls

**Structure:**

```
tests/
├── fixtures/                   # Stored API response fixtures
│   ├── weather/
│   │   ├── moscow_current.json
│   │   └── ...
│   ├── geocoding/
│   └── ...
├── openweathermap/
│   └── test_weather_client.py  # Tests using fixtures
└── geocode_maps/
    └── test_client.py
```

**Example test using fixtures:**

```python
import json
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "weather"


@pytest.fixture
def mockWeatherResponse():
    """Load cached API response"""
    return json.loads((FIXTURES_DIR / "moscow_current.json").read_text())


async def test_getWeatherByCity(mockWeatherResponse, httpx_mock):
    """Test weather client with golden data"""
    httpx_mock.add_response(json=mockWeatherResponse)

    client = OpenWeatherMapClient(apiKey="test-key")
    result = await client.getWeatherByCity("Moscow", "RU")
    assert result.current.temp > -60
```

### Writing New Tests

**Unit test example:**

```python
"""Tests for MyNewHandler"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from internal.bot.common.handlers.my_handler import MyNewHandler
from internal.bot.common.handlers.base import HandlerResultStatus


@pytest.fixture
def myHandler():
    """Create handler with mocked dependencies"""
    configManager = MagicMock()
    configManager.getBotConfig.return_value = {}
    database = MagicMock()
    botProvider = MagicMock()
    return MyNewHandler(configManager=configManager, database=database, botProvider=botProvider)


async def test_skipsIrrelevantMessages(myHandler):
    """Handler should skip messages that don't apply to it"""
    ensuredMessage = MagicMock()
    updateObj = MagicMock()
    myHandler.sendMessage = AsyncMock()

    # Configure message to not be handled
    ensuredMessage.text = "irrelevant"

    result = await myHandler.newMessageHandler(ensuredMessage, updateObj)
    assert result == HandlerResultStatus.SKIPPED
    myHandler.sendMessage.assert_not_called()
```

**Integration test example:**

```python
"""Integration tests for database wrapper"""

import pytest
import tempfile
import os
from internal.database import Database


@pytest.fixture
def tempDb():
    """Create a temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        dbPath = f.name

    db = Database(config={
        "default": "default",
        "providers": {"default": {"provider": "sqlite3", "parameters": {"dbPath": dbPath, "readOnly": False}}},
    })
    yield db

    os.unlink(dbPath)


def test_createAndGetChat(tempDb):
    """Test chat creation and retrieval"""
    tempDb.ensureChatExists(chatId=-100123, chatType="group", title="Test Chat")
    chat = tempDb.getChat(chatId=-100123)
    assert chat is not None
    assert chat["title"] == "Test Chat"
```

### Test Markers

Configure special markers in [`pyproject.toml`](pyproject.toml:66):

```python
@pytest.mark.slow        # Mark slow tests (skipped with -m "not slow")
@pytest.mark.performance # Performance benchmarks
@pytest.mark.benchmark   # Benchmark tests
@pytest.mark.memory      # Memory profiling tests
@pytest.mark.stress      # Stress tests
```

---

## 10. Code Quality

### Naming Conventions

The project enforces strict naming conventions Violating these is grounds for rejection in code review

| Construct | Convention | Example |
|---|---|---|
| Variables | `camelCase` | `chatId`, `userMessage`, `botToken` |
| Function arguments | `camelCase` | `configManager`, `ensuredMessage` |
| Local variables | `camelCase` | `resultText`, `spamScore` |
| Functions/Methods | `camelCase` | `getChatSettings()`, `handleMessage()` |
| Class fields | `camelCase` | `self.dbWrapper`, `self.maxCacheSize` |
| Class names | `PascalCase` | `Database`, `HandlersManager`, `CacheService` |
| Constants | `UPPER_CASE` | `DEFAULT_TIMEOUT`, `API_BASE_URL`, `MAX_RETRIES` |
| Module-level vars | `camelCase` or `UPPER_CASE` | `logger`, `DEFAULT_THREAD_ID` |

### Docstring Requirements

**Every** module, class, method, function, and non-obvious class field **must** have a docstring Be concise but always document all args and the return type

**Module docstring:**

```python
"""
My module providing something useful

This module implements X, Y, and Z functionality for the Gromozeka bot.
"""
```

**Class docstring:**

```python
class MyClass:
    """Short description of the class

    Longer description explaining the purpose, key design decisions,
    and usage context.

    Attributes:
        myField: Description of the field
        anotherField: Description

    Example:
        >>> obj = MyClass(config={...})
        >>> result = obj.doSomething()
    """
```

**Method/function docstring:**

```python
def myFunction(self, chatId: int, value: str) -> Optional[str]:
    """Brief description of what this does

    Longer description if needed for complex logic.

    Args:
        chatId: The chat ID to look up
        value: The value to process

    Returns:
        The processed result, or None if not found

    Raises:
        ValueError: If chatId is negative
    """
```

### Type Hints

**Always** write type hints for:
- All function/method arguments
- Return types
- Local variables when the type is not obvious

```python
# Good
def processMessage(self, chatId: int, message: str, ttl: Optional[int] = None) -> bool:
    result: Optional[str] = None
    processed: bool = False
    return processed

# Bad - no type hints
def processMessage(self, chat_id, message, ttl=None):
    ...
```

### Linting & Formatting

The project uses four code quality tools configured in [`pyproject.toml`](pyproject.toml)

| Tool | Purpose | Config |
|---|---|---|
| **Black** | Code formatter | 120 char line length, Python 3.12 target |
| **isort** | Import sorter | Black-compatible profile |
| **Flake8** | Style/error linter | 120 char limit, select `B,C,E,F,W,B950` |
| **Pyright** | Static type checker | `basic` mode, venv-aware |

**Import order** (enforced by isort)

```python
# 1. FUTURE imports
from __future__ import annotations

# 2. STDLIB imports
import asyncio
import logging
from typing import Optional

# 3. THIRDPARTY imports
import httpx
import telegram

# 4. FIRSTPARTY imports (internal/, lib/)
from internal.config.manager import ConfigManager

# 5. LOCALFOLDER (relative imports)
from .base import BaseBotHandler
```

### Make Commands

All quality checks and workflows are available via `make`

```bash
# Format code (Black + isort)
make format

# Run linters (Flake8 + isort check + Pyright)
make lint

# Run all tests
make test

# Run tests with verbose output
make test V=1

# Re-run only failing tests
make test-failed

# Run tests with HTML coverage report
make coverage

# Format + lint check (good for CI)
make check

# Install dependencies into venv
make install

# Update requirements.txt from current venv
make freeze-requirements

# Show outdated packages
make list-outdated-requirements

# Clean venv and __pycache__
make clean

# Show all available commands
make help
```

**Required workflow before committing** (enforced by code review)

```bash
make format lint    # Fix formatting + check for issues
make test           # Ensure all tests pass
```

---

## 11. Deployment

### Prerequisites

- Python 3.12+
- Virtual environment with all dependencies
- Configured TOML config file(s)
- Bot token from @BotFather (Telegram) or Max Developer Portal

### Setup

```bash
# 1. Clone the repo
git clone <repo-url> gromozeka
cd gromozeka

# 2. Create venv and install deps
make install

# 3. Create your config directory
mkdir -p my-config

# 4. Create main config with your secrets
cat > my-config/config.toml << 'EOF'
[bot]
mode = "telegram"
token = "YOUR_BOT_TOKEN"
bot_owners = ["your_username"]
spam-button-salt = "random-secret-salt-here"

[database]
default = "default"

[database.providers.default]
provider = "sqlite3"

[database.providers.default.parameters]
dbPath = "bot_data.db"
readOnly = false
timeout = 30
useWal = true

[models.providers.openrouter]
type = "openrouter"
api-key = "YOUR_OPENROUTER_KEY"

[models.models.main]
provider = "openrouter"
model_id = "mistralai/mistral-7b-instruct"
temperature = 0.7
context = 32768
enabled = true
EOF

# 5. Verify configuration loads correctly
./venv/bin/python3 main.py \
    --config-dir configs/00-defaults \
    --config my-config/config.toml \
    --print-config
```

### Running the Bot

```bash
# Standard start
./venv/bin/python3 main.py \
    --config-dir configs/00-defaults \
    --config my-config/config.toml

# Daemon mode (background process)
./venv/bin/python3 main.py \
    --config-dir configs/00-defaults \
    --config my-config/config.toml \
    --daemon \
    --pid-file /var/run/gromozeka.pid

# With .env file for secrets
./venv/bin/python3 main.py \
    --config-dir configs/00-defaults \
    --config my-config/config.toml \
    --dotenv-file /etc/gromozeka/.env
```

### Storage Directory

By default, the bot changes its working directory to the `root-dir` specified in `[application]` All relative paths (database, logs) are relative to this directory

```toml
[application]
root-dir = "/var/lib/gromozeka"   # All files created here

[database.providers.default.parameters]
dbPath = "bot_data.db"            # -> /var/lib/gromozeka/bot_data.db

[logging]
file = "logs/gromozeka.log"       # -> /var/lib/gromozeka/logs/gromozeka.log
```

### Systemd Service Example

```ini
# /etc/systemd/system/gromozeka.service
[Unit]
Description=Gromozeka Telegram Bot
After=network.target

[Service]
Type=simple
User=gromozeka
WorkingDirectory=/opt/gromozeka
ExecStart=/opt/gromozeka/venv/bin/python3 main.py \
    --config-dir /opt/gromozeka/configs/00-defaults \
    --config /etc/gromozeka/config.toml \
    --dotenv-file /etc/gromozeka/.env
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl enable gromozeka
sudo systemctl start gromozeka
sudo journalctl -u gromozeka -f
```

### Production Config Tips

```toml
[application]
root-dir = "/var/lib/gromozeka"

[logging]
level = "WARNING"    # Reduce verbosity in production
file = "logs/gromozeka.log"
error-file = "logs/gromozeka.err.log"
rotate = true

[database.providers.default.parameters]
timeout = 60
useWal = true

[ratelimiter.ratelimiters.default]
type = "SlidingWindow"
[ratelimiter.ratelimiters.default.config]
windowSeconds = 5
maxRequests = 10     # Increase for production volume
```

### Environment Variables

Sensitive values should always be provided via environment variables or `.env` file

```bash
# .env file example
TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
OPENROUTER_API_KEY=sk-or-v1-...
OPENWEATHERMAP_API_KEY=abc123...
YANDEX_API_KEY=AQVN...
YANDEX_FOLDER_ID=b1g...
GEOCODE_MAPS_API_KEY=...
```

```toml
# Reference in TOML config
[bot]
token = "${TELEGRAM_BOT_TOKEN}"

[models.providers.openrouter]
api-key = "${OPENROUTER_API_KEY}"
```

---

## 12. Common Development Tasks

### 12.1 Adding a New Handler

1. **Create the handler file** See [Section 6 - Creating a New Handler](#how-to-create-a-new-handler) for the complete template.

2. **Register in [`HandlersManager`](internal/bot/common/handlers/manager.py:249)**

```python
# In internal/bot/common/handlers/manager.py

# Add import at top
from .my_handler import MyNewHandler

# In HandlersManager.__init__, add to self.handlers list:
(MyNewHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.PARALLEL),
```

3. **Write tests** in `tests/bot/` or alongside the handler file

4. **Run the quality pipeline**

```bash
make format lint
make test
```

### 12.2 Adding a New API Integration

Let's say you want to integrate the "CoolAPI" service

**Step 1**: Create the library module

```
lib/
└── coolapi/
    ├── __init__.py
    ├── client.py       # CoolApiClient class
    ├── models.py       # Response data models
    └── README.md       # Document the integration
```

**Step 2**: Implement the client following the established pattern

```python
# lib/coolapi/client.py
"""CoolAPI async client with caching and rate limiting"""

import logging
from typing import Optional

import httpx

from lib.cache import CacheInterface, NullCache
from lib.rate_limiter import RateLimiterManager

from .models import CoolApiResponse

logger = logging.getLogger(__name__)


class CoolApiClient:
    """Async client for CoolAPI

    Args:
        apiKey: API authentication key
        cache: Optional cache for responses
        cacheTtl: Cache TTL in seconds (default: 3600)
        requestTimeout: HTTP timeout in seconds (default: 10)
        rateLimiterQueue: Rate limiter queue name
    """

    API_BASE: str = "https://api.coolservice.example.com/v1"

    def __init__(
        self,
        apiKey: str,
        cache: Optional[CacheInterface] = None,
        cacheTtl: Optional[int] = 3600,
        requestTimeout: int = 10,
        rateLimiterQueue: str = "coolapi",
    ) -> None:
        """Initialize CoolAPI client

        Args:
            apiKey: API authentication key
            cache: Optional cache implementation
            cacheTtl: Cache TTL in seconds
            requestTimeout: HTTP request timeout in seconds
            rateLimiterQueue: Rate limiter queue to use
        """
        self.apiKey = apiKey
        self.cache = cache or NullCache()
        self.cacheTtl = cacheTtl
        self.requestTimeout = requestTimeout
        self.rateLimiterQueue = rateLimiterQueue
        self._rateLimiter = RateLimiterManager.getInstance()

    async def getData(self, query: str) -> Optional[CoolApiResponse]:
        """Fetch data from CoolAPI

        Args:
            query: Search query string

        Returns:
            CoolApiResponse if successful, None on error
        """
        cacheKey: str = f"coolapi:{query}"
        cached = await self.cache.get(cacheKey, ttl=self.cacheTtl)
        if cached is not None:
            return cached

        await self._rateLimiter.applyLimit(self.rateLimiterQueue)

        async with httpx.AsyncClient(timeout=self.requestTimeout) as client:
            response = await client.get(
                f"{self.API_BASE}/data",
                params={"q": query, "key": self.apiKey},
            )
            response.raise_for_status()
            data = CoolApiResponse(**response.json())

        await self.cache.set(cacheKey, data)
        return data
```

**Step 3**: Add a config section in `configs/00-defaults/00-config.toml`

```toml
[coolapi]
enabled = false
api-key = "${COOLAPI_KEY}"
cache-ttl = 3600
request-timeout = 10
ratelimiter-queue = "coolapi"
```

**Step 4**: Add a rate limiter queue

```toml
[ratelimiter.ratelimiters.coolapi]
type = "SlidingWindow"
[ratelimiter.ratelimiters.coolapi.config]
windowSeconds = 60
maxRequests = 30

[ratelimiter.queues]
coolapi = "coolapi"
```

**Step 5**: Add a `getCoolApiConfig()` method to [`ConfigManager`](internal/config/manager.py:59).

**Step 6**: Create a handler that uses the client and register it in [`HandlersManager`](internal/bot/common/handlers/manager.py:177).

**Step 7**: Write tests using the golden data fixture pattern

### 12.3 Adding a New LLM Provider

**Step 1**: Create the provider file

```python
# lib/ai/providers/my_provider.py
"""My LLM provider implementation"""

from typing import Any, Dict, Optional, Sequence

from lib.ai.abstract import AbstractLLMProvider, AbstractModel
from lib.ai.models import LLMAbstractTool, ModelMessage, ModelResultStatus, ModelRunResult


class MyProviderModel(AbstractModel):
    """A model served by MyProvider

    Args:
        provider: The parent provider instance
        modelId: Unique model identifier
        modelVersion: Model version string
        temperature: Sampling temperature
        contextSize: Max context tokens
        extraConfig: Additional configuration dict
    """

    def __init__(
        self,
        provider: "MyProvider",
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ):
        """Initialize the model"""
        super().__init__(provider, modelId, modelVersion, temperature, contextSize, extraConfig)

    async def _generateText(
        self,
        messages: Sequence[ModelMessage],
        tools: Optional[Sequence[LLMAbstractTool]] = None,
    ) -> ModelRunResult:
        """Generate text using MyProvider API

        Args:
            messages: Input message sequence
            tools: Optional tool definitions

        Returns:
            ModelRunResult with text and status
        """
        # TODO: Implement actual API call here
        raise NotImplementedError("Implement me")

    async def generateImage(self, messages: Sequence[ModelMessage]) -> ModelRunResult:
        """Generate image (not supported by this provider)

        Args:
            messages: Input message sequence

        Returns:
            ModelRunResult with ERROR status
        """
        return ModelRunResult(
            rawResult=None,
            status=ModelResultStatus.ERROR,
            error=NotImplementedError("Image generation not supported by MyProvider"),
        )


class MyProvider(AbstractLLMProvider):
    """Provider for MyLLM service

    Args:
        config: Provider configuration dict with api-key and optional base-url
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize provider with config

        Args:
            config: Configuration dict (must contain 'api-key')
        """
        super().__init__(config)
        self.apiKey: str = config["api-key"]
        self.baseUrl: str = config.get("base-url", "https://api.myllm.example.com")

    def addModel(
        self,
        name: str,
        modelId: str,
        modelVersion: str,
        temperature: float,
        contextSize: int,
        extraConfig: Dict[str, Any] = {},
    ) -> AbstractModel:
        """Add a model to this provider

        Args:
            name: Human-readable model name for registry
            modelId: Provider-specific model ID
            modelVersion: Model version string
            temperature: Sampling temperature
            contextSize: Maximum context token count
            extraConfig: Additional model configuration

        Returns:
            Newly created model instance
        """
        model = MyProviderModel(self, modelId, modelVersion, temperature, contextSize, extraConfig)
        self.models[name] = model
        return model
```

**Step 2**: Register in [`LLMManager._initProviders()`](lib/ai/manager.py:36)

```python
# In lib/ai/manager.py, add import:
from .providers.my_provider import MyProvider

# In _initProviders(), add to providerTypes dict:
providerTypes = {
    "yc-openai": YcOpenaiProvider,
    "openrouter": OpenrouterProvider,
    "yc-sdk": YcAIProvider,
    "custom-openai": CustomOpenAIProvider,
    "my-provider": MyProvider,    # Add here
}
```

**Step 3**: Configure in TOML

```toml
[models.providers.my-llm]
type = "my-provider"
api-key = "${MY_LLM_API_KEY}"
base-url = "https://api.myllm.example.com"

[models.models.my-model]
provider = "my-llm"
model_id = "myllm-v1"
model_version = "latest"
temperature = 0.5
context = 16384
enabled = true
support_images = false
support_tools = false
tier = "free"
```

### 12.4 Adding a Database Migration

> ⚠️ **Critical**: Always verify the current highest version before creating a migration

**Step 1**: Find the highest current migration version

```bash
ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
# Example output: migration_012_unify_cache_tables.py
# -> Next version is 013
```

**Step 2**: Create the migration file

```python
# internal/database/migrations/versions/migration_013_my_change.py
"""Migration 013 - Add my new column"""

import sqlite3

from internal.database.migrations.base import BaseMigration


class Migration(BaseMigration):
    """Adds my_column to the chats table

    This migration adds a new column to support the XYZ feature.
    """

    version: int = 13
    description: str = "Add my_column to chats table"

    async def up(self, sqlProvider: BaseSQLProvider) -> None:
        """Apply migration: add my_column

        Args:
            sqlProvider: SQL provider for executing SQL
        """
        await sqlProvider.execute("""
            ALTER TABLE chats
            ADD COLUMN my_column TEXT DEFAULT NULL
        """)

    async def down(self, sqlProvider: BaseSQLProvider) -> None:
        """Rollback migration

        Note: SQLite before 3.35 does not support DROP COLUMN.
        Consider a table-rebuild approach for older SQLite versions.

        Args:
            sqlProvider: SQL provider for executing SQL
        """
        # SQLite 3.35+: await sqlProvider.execute("ALTER TABLE chats DROP COLUMN my_column")
        pass
```

**Step 3**: The migration manager auto-discovers files in the `versions/` directory No manual registration needed.

**Step 4**: Run the bot — migrations are applied automatically on startup

**Step 5**: Update any schema documentation in `docs/`

### 12.5 Adding a New Chat Setting

Chat settings are key-value pairs stored per-chat and cached in [`CacheService`](internal/services/cache/service.py:88)

**Step 1**: Add the key to `ChatSettingsKey` enum in [`internal/bot/models/chat_settings.py`](internal/bot/models/chat_settings.py)

```python
class ChatSettingsKey(StrEnum):
    # ... existing keys ...
    MY_NEW_SETTING = "my-new-setting"
```

**Step 2**: Add the setting metadata in `getChatSettingsInfo()` for type/validation info

**Step 3**: Add a default value in [`configs/00-defaults/bot-defaults.toml`](configs/00-defaults/bot-defaults.toml)

```toml
[bot.defaults]
my-new-setting = "default_value"
```

**Step 4**: Use it in your handler

```python
settings = self.getChatSettings(chatId=ensuredMessage.recipient.id)
myValue: str = settings.get(ChatSettingsKey.MY_NEW_SETTING, "default_value")
```

---

## Appendix: Quick Reference

### Key File Locations

| What | Where |
|---|---|
| Entry point | [`main.py`](main.py) |
| Bot orchestrator class | [`main.py:31`](main.py:31) → `GromozekBot` |
| Multi-platform bot client | [`internal/bot/common/bot.py:31`](internal/bot/common/bot.py:31) → `TheBot` |
| Base handler class | [`internal/bot/common/handlers/base.py:110`](internal/bot/common/handlers/base.py:110) → `BaseBotHandler` |
| Handler result enum | [`internal/bot/common/handlers/base.py:82`](internal/bot/common/handlers/base.py:82) → `HandlerResultStatus` |
| Handler manager | [`internal/bot/common/handlers/manager.py:177`](internal/bot/common/handlers/manager.py:177) → `HandlersManager` |
| Config manager | [`internal/config/manager.py:59`](internal/config/manager.py:59) → `ConfigManager` |
| Database | [`internal/database/database.py`](internal/database/database.py) → `Database` |
| Database source config | [`internal/database/database.py`](internal/database/database.py) → `SourceConfig` |
| Cache service | [`internal/services/cache/service.py:88`](internal/services/cache/service.py:88) → `CacheService` |
| LLM manager | [`lib/ai/manager.py:17`](lib/ai/manager.py:17) → `LLMManager` |
| LLM abstract model | [`lib/ai/abstract.py:19`](lib/ai/abstract.py:19) → `AbstractModel` |
| LLM abstract provider | [`lib/ai/abstract.py:257`](lib/ai/abstract.py:257) → `AbstractLLMProvider` |
| Rate limiter manager | [`lib/rate_limiter/manager.py:12`](lib/rate_limiter/manager.py:12) → `RateLimiterManager` |
| Cache interface | [`lib/cache/interface.py:15`](lib/cache/interface.py:15) → `CacheInterface[K, V]` |
| Migration base class | [`internal/database/migrations/base.py:9`](internal/database/migrations/base.py:9) → `BaseMigration` |
| Default config | [`configs/00-defaults/00-config.toml`](configs/00-defaults/00-config.toml) |
| Bot defaults config | [`configs/00-defaults/bot-defaults.toml`](configs/00-defaults/bot-defaults.toml) |
| Custom handler example | [`internal/bot/common/handlers/example_custom_handler.py`](internal/bot/common/handlers/example_custom_handler.py) |
| Markdown parser | [`lib/markdown/parser.py`](lib/markdown/parser.py) → `MarkdownParser` |
| Max Bot client | [`lib/max_bot/client.py:75`](lib/max_bot/client.py:75) → `MaxBotClient` |
| Weather client | [`lib/openweathermap/client.py:22`](lib/openweathermap/client.py:22) → `OpenWeatherMapClient` |
| Geocode client | [`lib/geocode_maps/client.py:26`](lib/geocode_maps/client.py:26) → `GeocodeMapsClient` |

### Startup Sequence

```
main()
  └── ConfigManager(configPath, configDirs, dotEnvFile)
        └── _loadConfig() → deep-merge all TOML files → substituteEnvVars()
  └── GromozekBot(configManager)
        ├── initLogging(loggingConfig)
        ├── DatabaseManager(dbConfig)
        │     └── Database(config)
        │           ├── _initializeMultiSource(config)  ← connection pool setup
        │           ├── _initializeProviders()          ← provider initialization
        │           └── _initDatabase()                 ← run pending migrations
        ├── LLMManager(modelsConfig)
        │     ├── _initProviders()   ← create provider instances
        │     └── _initModels()      ← register models per provider
        ├── LLMService.getInstance().injectLLMManager(llmManager)
        ├── RateLimiterManager.getInstance().loadConfig(rateLimiterConfig)
        └── TelegramBotApplication OR MaxBotApplication
              └── HandlersManager(configManager, database, botProvider)
                    ├── CacheService.getInstance().injectDatabase(db)
                    ├── StorageService.getInstance().injectConfig(configManager)
                    ├── QueueService.getInstance()
                    └── Initialize all handlers in order
  └── bot.run()  ← start async event loop, begin polling/webhook
```

### Common Mistakes to Avoid

1. **Never reuse migration version numbers** Always run `ls -V internal/database/migrations/versions/` first!

2. **Never guess config structure** Use `./venv/bin/python3 main.py --print-config` to see the merged result!

3. **Always run `make format lint` before committing** Failing CI wastes everyone's time!

4. **Don't call services before they're initialized** Singletons need injection (`injectDatabase()`, `injectConfig()`) before use!

5. **Don't bypass rate limiting for external API calls** Always call `await rateLimiter.applyLimit(queue)` first!

6. **Don't use `cd` in scripts** Always run scripts from the project root using `./venv/bin/python3 ...`!

7. **Don't skip docstrings** Every public module, class, method, and function needs one with Args/Returns!

8. **Don't use `snake_case` for variables/methods** The project enforces `camelCase` everywhere except class names (`PascalCase`) and constants (`UPPER_CASE`)!

9. **Don't block the event loop** All database and network calls must be async or run in a thread executor!

10. **Don't hardcode config values** Everything configurable must go through [`ConfigManager`](internal/config/manager.py:59) and TOML!

---

*This guide was written with love and enthusiasm by a Prinny If something is missing, wrong, or outdated — file an issue or update the docs directly Stay awesome! 🐧*