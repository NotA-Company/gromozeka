---
category: guide
description: "Entry point to the developer guides: project and architecture overview, directory structure, and quick reference."
---

# Getting Started

Start here: what Gromozeka is, how the repository is organized, and a quick reference for key files and the startup flow.

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
│  yandex_search/  geocode_maps/  bayes_filter/  markdown/     │
│  sandbox/  divination/  stats/                                │
└───────────────────────────────────────────────────────────────┘
```

### Key Design Patterns

| Pattern | Where Used | Purpose |
|---|---|---|
| Singleton | [`CacheService`](/internal/services/cache/service.py:88), [`QueueService`](/internal/services/queue_service/service.py), [`RateLimiterManager`](/lib/rate_limiter/manager.py:12) | Shared state across handlers |
| Abstract Base Class | [`AbstractModel`](/lib/ai/abstract.py:47), [`AbstractLLMProvider`](/lib/ai/abstract.py:904), [`CacheInterface`](/lib/cache/interface.py:15), [`BaseMigration`](/internal/database/migrations/base.py:9) | Type-safe extensibility |
| Chain of Responsibility | Handler pipeline in [`HandlersManager`](/internal/bot/common/handlers/manager.py:382) | Sequential/parallel message processing |
| Multi-source Router | [`Database`](/internal/database/database.py) | Chat-to-database routing |
| Decorator-based Discovery | `@commandHandlerV2` decorator, [`CommandHandlerMixin`](/internal/bot/models) | Auto-discovery of bot commands |
| Golden Data Testing | [`tests/`](/tests/) | Deterministic API test replay |

---

## 3. Directory Structure

### Repository Root Files

```
gromozeka/
├── main.py                         # Entry point - GromozekBot orchestrator
├── run.sh                          # Shell script to start the bot
├── Makefile                        # Dev commands (format, lint, test, etc.)
├── pyproject.toml                  # Tool configuration (black, flake8, pyright, pytest, isort)
├── requirements.txt                # Python dependencies
│
```

### configs/ Directory

```
├── configs/                        # Hierarchical TOML configuration
│   ├── 00-defaults/                # Base default configs (loaded first)
│   │   ├── 00-config.toml          # Core settings (bot, db, rate limiter, APIs)
│   │   └── bot-defaults.toml       # Per-chat-type and global bot defaults
│   ├── common/                     # Common environment overrides
│   ├── local/                      # Local development overrides
│   ├── local-telegram/             # Local Telegram-specific overrides
│   ├── local-max/                  # Local Max-specific overrides
│   ├── prod/                       # Production overrides
│   ├── prod-telegram/              # Production Telegram-specific overrides
│   └── prod-max/                   # Production Max-specific overrides

```

### internal/ Directory

```
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
│   │   │   │   ├── user_memories.py    # User memories management handler
│   │   │   │   ├── dev_commands.py # Developer/admin command handler
│   │   │   │   ├── weather.py      # Weather integration handler
│   │   │   │   ├── yandex_search.py# Yandex search integration handler
│   │   │   │   ├── topic_manager.py# Telegram topic management handler
│   │   │   │   ├── react_on_user.py# User reaction handler
│   │   │   │   ├── delete_from_user.py  # Delete messages on user request (Telegram only)
│   │   │   │   ├── resender.py     # Message forwarding handler
│   │   │   │   ├── divination.py   # /taro and /runes divination handler (if divination.enabled)
│   │   │   │   ├── sandbox.py      # Sandboxed code execution handler (if sandbox.enabled)
│   │   │   │   ├── chat_search.py  # /search + message search LLM tools (if search-history.enabled)
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
```

#### internal/config/ and internal/database/

```
│   ├── config/                     # Configuration management
│   │   └── manager.py              # ConfigManager - hierarchical TOML loader
│   │
│   ├── database/                   # Database layer
│   │   ├── database.py             # Database - main database interface
│   │   ├── manager.py              # DatabaseManager - lifecycle management
│   │   ├── models.py               # TypedDict models for DB rows
│   │   ├── bayes_storage.py        # Bayes filter DB storage
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
│   │   │   ├── common.py           # Common functions repository
│   │   │   ├── delayed_tasks.py    # Delayed tasks repository
│   │   │   ├── media_attachments.py # Media attachments repository
│   │   │   ├── spam.py             # Spam repository
│   │   │   ├── chat_search.py      # Chat search (filter + semantic) repository
│   │   │   ├── chat_embeddings.py  # Message embeddings repository
│   │   │   ├── divinations.py      # Divination readings + layout discovery repository
│   │   │   └── user_memories.py    # User memories repository
│   │   └── migrations/             # Migration system
│   │       ├── base.py             # BaseMigration abstract class
│   │       ├── manager.py          # MigrationManager - auto-discovery + apply
│   │       ├── create_migration.py # Script to scaffold new migrations
│   │       └── versions/           # Migration files (migration_001 to migration_029)
│   │
```

#### internal/services/ and internal/models/

```
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
```

### lib/ Directory

```
├── lib/                            # Reusable library components
│   ├── ai/                         # LLM abstraction layer
│   │   ├── abstract.py             # AbstractModel, AbstractLLMProvider
│   │   ├── manager.py              # LLMManager - provider+model registry
│   │   ├── models.py               # ModelMessage, ModelRunResult, etc.
│   │   └── providers/              # Concrete LLM provider implementations
│   │       ├── basic_openai_provider.py
│   │       ├── custom_openai_provider.py
│   │       ├── fastembed_provider.py
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
```

#### lib/markdown/ and lib/sandbox/

```
│   ├── markdown/                   # Custom Markdown parser
│   │   ├── parser.py               # MarkdownParser (main entry point)
│   │   ├── tokenizer.py            # Tokenizer
│   │   ├── block_parser.py         # Block-level parser
│   │   ├── inline_parser.py        # Inline-level parser
│   │   ├── renderer.py             # HTMLRenderer, MarkdownV2Renderer
│   │   └── ast_nodes.py            # AST node types
│   ├── sandbox/                    # Sandboxed code execution (Docker)
│   │   ├── manager.py              # SandboxManager singleton
│   │   ├── config.py               # Configuration dataclasses
│   │   ├── types.py                # Public dataclasses (RunResult, etc.)
│   │   ├── enums.py                # RuntimeName, BackendName
│   │   ├── errors.py               # Exception hierarchy
│   │   ├── locks.py                # Per-session FIFO locks, global semaphore
│   │   ├── storage.py              # Workspace path resolution, atomic writes
│   │   ├── gc.py                   # Garbage collector for expired sessions
│   │   ├── backends/               # Execution backends
│   │   │   ├── base.py             # SandboxBackend ABC
│   │   │   └── docker.py           # Docker backend
│   │   ├── runtimes/               # Language runtimes
│   │   │   ├── base.py             # Runtime ABC
│   │   │   └── python/             # Python runtime
│   │   │       └── runtime.py      # PythonRuntime
│   │   └── metadata/               # Session/run metadata
│   │       ├── base.py             # MetadataStore ABC
│   │       └── filesystem.py      # Filesystem-backed store
│   ├── logging_utils.py            # Logging helpers (initLogging)
│   └── utils.py                    # Shared utility functions
│
```

### tests/ and docs/ Directories

```
├── tests/                          # Test suite (all tests live here)
│   ├── conftest.py                 # Shared pytest fixtures
│   ├── utils.py                    # Test utilities
│   ├── bot/                        # Bot handler tests
│   ├── config/                     # Config tests
│   ├── database/                   # Database tests
│   ├── fixtures/                    # Golden data fixtures (JSON)
│   ├── integration/                # Cross-cutting integration tests
│   ├── lib/                        # Library tests (mirrors lib/ structure)
│   │   ├── ai/                     # LLM / AI tests + golden data
│   │   ├── markdown/               # Markdown parser tests
│   │   ├── openweathermap/          # Weather client tests + golden data
│   │   └── ...                     # Other lib package tests
│   ├── models/                     # Model tests
│   ├── services/                   # Service layer tests
│   └── verification/               # Cross-cutting verification tests
│
├── docs/                           # Project documentation
│   └── reports/                    # Development reports and ADRs
```

---

## Appendix: Quick Reference

### Key File Locations

| What | Where |
|---|---|
| Entry point | [`main.py`](/main.py) |
| Bot orchestrator class | [`main.py:31`](/main.py:31) → `GromozekBot` |
| Multi-platform bot client | [`internal/bot/common/bot.py:31`](/internal/bot/common/bot.py:31) → `TheBot` |
| Base handler class | [`internal/bot/common/handlers/base.py:110`](/internal/bot/common/handlers/base.py:110) → `BaseBotHandler` |
| Handler result enum | [`internal/bot/common/handlers/base.py:82`](/internal/bot/common/handlers/base.py:82) → `HandlerResultStatus` |
| Handler manager | [`internal/bot/common/handlers/manager.py:382`](/internal/bot/common/handlers/manager.py:382) → `HandlersManager` |
| Config manager | [`internal/config/manager.py:59`](/internal/config/manager.py:59) → `ConfigManager` |
| Database | [`internal/database/database.py`](/internal/database/database.py) → `Database` |
| Database source config | [`internal/database/database.py`](/internal/database/database.py) → `SourceConfig` |
| Cache service | [`internal/services/cache/service.py:88`](/internal/services/cache/service.py:88) → `CacheService` |
| LLM manager | [`lib/ai/manager.py:49`](/lib/ai/manager.py:49) → `LLMManager` |
| LLM abstract model | [`lib/ai/abstract.py:47`](/lib/ai/abstract.py:47) → `AbstractModel` |
| LLM abstract provider | [`lib/ai/abstract.py:904`](/lib/ai/abstract.py:904) → `AbstractLLMProvider` |
| Rate limiter manager | [`lib/rate_limiter/manager.py:12`](/lib/rate_limiter/manager.py:12) → `RateLimiterManager` |
| Cache interface | [`lib/cache/interface.py:15`](/lib/cache/interface.py:15) → `CacheInterface[K, V]` |
| Migration base class | [`internal/database/migrations/base.py:9`](/internal/database/migrations/base.py:9) → `BaseMigration` |
| Default config | [`configs/00-defaults/00-config.toml`](/configs/00-defaults/00-config.toml) |
| Bot defaults config | [`configs/00-defaults/bot-defaults.toml`](/configs/00-defaults/bot-defaults.toml) |
| Custom handler example | [`internal/bot/common/handlers/example_custom_handler.py`](/internal/bot/common/handlers/example_custom_handler.py) |
| Markdown parser | [`lib/markdown/parser.py`](/lib/markdown/parser.py) → `MarkdownParser` |
| Max Bot client | [`lib/max_bot/client.py:75`](/lib/max_bot/client.py:75) → `MaxBotClient` |
| Weather client | [`lib/openweathermap/client.py:22`](/lib/openweathermap/client.py:22) → `OpenWeatherMapClient` |
| Geocode client | [`lib/geocode_maps/client.py:26`](/lib/geocode_maps/client.py:26) → `GeocodeMapsClient` |

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

10. **Don't hardcode config values** Everything configurable must go through [`ConfigManager`](/internal/config/manager.py:59) and TOML!

---

*This guide was written with love and enthusiasm by a Prinny If something is missing, wrong, or outdated — file an issue or update the docs directly Stay awesome!*
