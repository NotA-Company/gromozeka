# Gromozeka — Architecture & Design Decisions

> **Audience:** LLM agents, dood!  
> **Purpose:** Architecture Decision Records, component dependencies, design patterns, dood!  
> **Self-contained:** Everything needed for architecture understanding is here, dood!

---

## Table of Contents

1. [Architecture Decision Records](#1-architecture-decision-records)
2. [Dependency Map](#2-dependency-map)
3. [Design Patterns](#3-design-patterns)

---

## 1. Architecture Decision Records

### ADR-001: Singleton Services

**Decision:** `CacheService`, `QueueService`, `LLMService`, `StorageService`, `RateLimiterManager` are all singletons, dood!

**Why:** Single instance ensures consistent state across all handlers and avoids duplicate resource usage, dood!

**Constraint:** Always use `getInstance()` — never `SomeService()` directly:
```python
# CORRECT, dood!
cache = CacheService.getInstance()

# WRONG — creates duplicate state, dood!
cache = CacheService()
```

**Thread safety:** All singletons use `RLock` for thread-safe instantiation, dood!

**Singleton pattern (MUST preserve when modifying services):**
```python
class MyService:
    """Singleton service, dood!"""

    _instance: Optional["MyService"] = None
    _lock: RLock = RLock()

    def __new__(cls) -> "MyService":
        """Create or return singleton instance, dood!"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize service once, dood!"""
        if hasattr(self, "initialized"):
            return
        self.initialized = True
        # ... actual init ...

    @classmethod
    def getInstance(cls) -> "MyService":
        """Get the singleton instance, dood!

        Returns:
            The singleton MyService instance
        """
        return cls()
```

---

### ADR-002: Handler Chain Pattern

**Decision:** Messages flow through an ordered list of `BaseBotHandler` subclasses via [`HandlersManager`](../../internal/bot/common/handlers/manager.py:892), dood!

**Why:** Separation of concerns — each handler does one thing. Easy to add new features without modifying existing handlers, dood!

**Chain order (CRITICAL, dood!):**
1. `MessagePreprocessorHandler` — SEQUENTIAL — saves message + media
2. `SpamHandler` — SEQUENTIAL — spam check before all others
3. `ConfigureCommandHandler` — PARALLEL — settings config
4. `SummarizationHandler` — PARALLEL — summarization
5. `UserDataHandler` — PARALLEL — user data
6. `DevCommandsHandler` — PARALLEL — debug commands
7. `MediaHandler` — PARALLEL — media processing
8. `CommonHandler` — PARALLEL — standard commands
9. `HelpHandler` — PARALLEL — help command
10. (Telegram only) `ReactOnUserMessageHandler` — PARALLEL
11. (Telegram only) `TopicManagerHandler` — PARALLEL
12. (if enabled) `WeatherHandler`, `YandexSearchHandler`, `ResenderHandler` — PARALLEL
13. (custom handlers) — PARALLEL
14. `LLMMessageHandler` — SEQUENTIAL — **MUST BE LAST**

**Return values:** Handlers return [`HandlerResultStatus`](../../internal/bot/common/handlers/base.py:82):
- `FINAL` — stop chain, success
- `SKIPPED` — continue (most common)
- `NEXT` — continue (processed but need more)
- `ERROR` — continue (recoverable error)
- `FATAL` — stop chain, error

---

### ADR-003: Multi-Platform Abstraction (`TheBot`)

**Decision:** [`TheBot`](../../internal/bot/common/bot.py:31) wraps both Telegram and Max Messenger APIs behind a unified interface, dood!

**Why:** Handlers don't need to know which platform they're on, dood!

**Constraint:** Never call Telegram/Max APIs directly from handlers. Always use `self.sendMessage()`, `self.deleteMessage()`, etc. from `BaseBotHandler`, dood!

---

### ADR-004: Multi-Source Database Routing

**Decision:** [`DatabaseWrapper`](../../internal/database/wrapper.py) supports multiple SQLite sources with internal routing, dood!

**Why:** Allows read replicas, separate databases for different data types, cross-bot data reading, dood!

**Architecture Principles:**
- **Single Class Design**: All routing logic internal to `DatabaseWrapper` — no separate Router class
- **Simple Priority Routing**: `dataSource` param → `chatId` mapping → default source
- **Readonly Protection**: Sources marked `readonly=True` reject write operations
- **Cross-Bot Communication**: Can read from external bot databases via `dataSource` param

**Config:** `[database.sources.*]` in TOML, routing via `dataSource` parameter on read methods:
```toml
[database]
default = "default"

[database.sources.default]
path = "bot_data.db"
readonly = false
pool-size = 5
timeout = 30

[database.sources.readonly]
path = "bot_data.db"
readonly = true
pool-size = 10
timeout = 10
```

**Method categories in `DatabaseWrapper`:**
- 19 chat-specific methods use routing
- 14 cross-chat methods handle multiple sources or use default
- 15 internal helper methods remain unchanged

**Implementation Details:**
- `ConnectionManager`: Manages connection pools per data source with thread-safe access
- Backward compatible: Works with legacy single database mode
- Optional `dataSource` parameter: Zero breaking changes

---

### ADR-005: LLM Provider Fallback

**Decision:** [`LLMManager`](../../lib/ai/manager.py:17) supports multiple providers with automatic fallback, dood!

**Why:** If primary LLM provider fails, automatically falls back to secondary, dood!

**Providers:** `yc-openai`, `openrouter`, `yc-sdk`, `custom-openai`.

---

### ADR-006: Command Discovery via Decorators

**Decision:** Commands are discovered via `@commandHandlerV2(...)` decorator on methods, dood!

**Why:** Zero-registration — add decorator, command is auto-discovered by `HandlersManager`, dood!

**Decorator location:** Imported from `internal.bot.models` as `commandHandlerV2`, dood!

---

### ADR-007: Configuration Layering

**Decision:** Config loads from multiple TOML files and merges them in order, dood!

**Why:** Separates defaults from environment-specific overrides, dood!

**Load order:** `--config` file first, then `--config-dir` files sorted alphabetically, dood!

**Merge behavior:** Later files override earlier ones. Nested dicts are merged recursively, dood!

---

### ADR-008: Cross-Source Aggregation with Intelligent Deduplication

**Decision:** Cross-source database queries use semantic deduplication keys per method type, dood!

**Why:** Prevents duplicates when aggregating data across multiple SQLite sources, dood!

**Deduplication Keys Strategy:**
- `getUserChats()`: `(userId, chat_id)` — user-chat relationship uniqueness
- `getAllGroupChats()`: `chat_id` — chat uniqueness
- `getSpamMessages()`: `(chat_id, message_id)` — message uniqueness within chat
- `getCacheStorage()`: `(namespace, key)` — cache entry uniqueness
- `getCacheEntry()`: First match (no deduplication) — performance optimization

**Error Handling:** Continue aggregation on individual source failures with warning logs, dood!

---

### ADR-009: Time-Based Media Group Completion Detection

**Decision:** Telegram media groups (albums) use time-based completion detection with configurable delay, dood!

**Why:** Telegram sends media groups as separate messages with same `media_group_id` but doesn't indicate when all items have arrived, dood!

**Solution:** Wait a configurable delay after the last media item is received before considering a media group complete.

**Architecture Choice:**
- **Per-Job Configuration**: Each `ResendJob` has its own `mediaGroupDelaySecs` parameter (default: 5.0 seconds)
- **Database Method**: `getMediaGroupLastUpdatedAt()` returns `MAX(created_at)` from `media_groups` table
- **Processing Logic**: `_dtCronJob` checks media group age before processing using `utils.getAgeInSecs()`

**Processing Flow:**
1. For each message with `media_group_id`, check if already processed
2. Get last updated timestamp using `getMediaGroupLastUpdatedAt()`
3. If age < `job.mediaGroupDelaySecs`, mark as pending and skip
4. If age >= `job.mediaGroupDelaySecs`, mark as processed and resend all media together

**Configuration:**
```toml
[[resender.jobs]]
id = "telegram-to-max"
sourceChatId = -1001234567890
targetChatId = 9876543210
mediaGroupDelaySecs = 5.0  # Optional, defaults to 5.0
```

**Edge Cases Handled:**
- **Slow uploads**: Each new media item updates timestamp, extending wait time
- **Fast uploads**: All media arrive quickly, processed together after delay
- **Single media**: Processed immediately if no `media_group_id`

---

### ADR-010: Chat Settings Audit Trail

**Decision:** `chat_settings` table includes `updated_by` column (INTEGER NOT NULL) to track which user last modified each setting, dood!

**Why:** Required for audit capability — knowing who changed what setting, dood!

**Implementation:**
- Migration `migration_010` adds `updated_by` column via table recreation pattern
- Existing data: `updated_by=0` set for all existing rows during migration
- `setChatSetting(chatId, key, value, *, updatedBy: int)` — `updatedBy` is required keyword-only argument

**API Design:**
- `getChatSetting(chatId, setting)` — returns `Optional[str]` (just the value for backward compatibility)
- `getChatSettings(chatId)` — returns `Dict[str, tuple[str, int]]` where tuple is `(value, updated_by)`
- This minimizes breaking changes while providing audit capability

---

## 2. Dependency Map

### 2.1 Component Dependency Graph

```
GromozekBot (main.py)
├── ConfigManager (internal/config/manager.py)
├── DatabaseManager (internal/database/manager.py)
│   └── DatabaseWrapper (internal/database/wrapper.py)
│       └── MigrationManager (internal/database/migrations/manager.py)
├── LLMManager (lib/ai/manager.py)
│   └── AbstractLLMProvider (lib/ai/abstract.py)
│       └── AbstractModel (lib/ai/abstract.py)
├── RateLimiterManager (lib/rate_limiter/manager.py)
└── BotApplication (Telegram or Max)
    └── HandlersManager (internal/bot/common/handlers/manager.py)
        ├── CacheService.getInstance() (internal/services/cache/service.py)
        ├── StorageService.getInstance() (internal/services/storage/service.py)
        ├── QueueService.getInstance() (internal/services/queue_service/service.py)
        └── [All Handler instances]
            └── BaseBotHandler (internal/bot/common/handlers/base.py)
                ├── CacheService.getInstance()
                ├── QueueService.getInstance()
                ├── StorageService.getInstance()
                ├── LLMService.getInstance() (internal/services/llm/service.py)
                ├── DatabaseWrapper (via self.db)
                ├── LLMManager (via self.llmManager)
                ├── ConfigManager (via self.configManager)
                └── TheBot (internal/bot/common/bot.py) [injected]
                    ├── CacheService.getInstance()
                    └── Platform API (Telegram ExtBot or MaxBotClient)
```

### 2.2 Service Initialization Order (Critical, dood!)

Services MUST be initialized in this order:

1. `ConfigManager` — first, everything needs config
2. `DatabaseManager` / `DatabaseWrapper` — second, services need DB
3. `LLMManager` — third, handlers need LLM
4. `RateLimiterManager.getInstance().loadConfig(...)` — fourth
5. `BotApplication` init — which triggers:
   - `HandlersManager.__init__()`:
     - `CacheService.getInstance()` + `cache.injectDatabase(db)`
     - `StorageService.getInstance()` + `storage.injectConfig(configManager)`
     - `QueueService.getInstance()`
     - All handler constructors (which get `CacheService`, `QueueService`, etc.)
6. `HandlersManager.injectBot(bot)` — injects `TheBot` into all handlers

### 2.3 What Breaks if You Modify These Files

| File Modified | What Could Break | Verification |
|---|---|---|
| [`internal/database/wrapper.py`](../../internal/database/wrapper.py) | All DB operations, all handlers that use `self.db` | `make test` — `tests/test_db_wrapper.py` |
| [`internal/bot/common/handlers/base.py`](../../internal/bot/common/handlers/base.py) | ALL handlers (they all inherit from `BaseBotHandler`) | Full `make test` |
| [`internal/bot/common/handlers/manager.py`](../../internal/bot/common/handlers/manager.py) | Handler chain order, command routing, parallelism | Full `make test` |
| [`internal/config/manager.py`](../../internal/config/manager.py) | Config loading for the entire app | Full `make test` |
| [`internal/services/cache/service.py`](../../internal/services/cache/service.py) | Chat settings, user data, admin caching | Full `make test` |
| [`lib/ai/abstract.py`](../../lib/ai/abstract.py) | ALL LLM provider implementations | `make test` — `tests/lib_ai/` |
| [`lib/ai/manager.py`](../../lib/ai/manager.py) | Model selection, provider init | `make test` — `tests/lib_ai/` |
| [`lib/ai/models.py`](../../lib/ai/models.py) | Message format, tool definitions | ALL handler tests that use LLM |
| [`lib/cache/interface.py`](../../lib/cache/interface.py) | All cache implementations | `make test` — cache tests |
| [`internal/bot/common/bot.py`](../../internal/bot/common/bot.py) | All message sending/receiving operations | Full `make test` |
| [`lib/markdown/parser.py`](../../lib/markdown/parser.py) | All message formatting in both platforms | Markdown tests in `lib/markdown/test/` |

### 2.4 Safe vs. Risky Modifications

#### Safe (isolated, dood!)
- Adding a new method to `DatabaseWrapper` without changing existing methods
- Adding a new handler file without modifying `manager.py`
- Adding a new config getter to `ConfigManager`
- Adding a new LLM provider to `lib/ai/providers/`
- Adding tests

#### Moderate Risk (dood!)
- Modifying `CacheService` internal data structures
- Changing handler execution order in `HandlersManager`
- Modifying `BaseBotHandler.sendMessage()` signature

#### High Risk (ALWAYS run full `make test`, dood!)
- Modifying `BaseBotHandler.__init__()` signature
- Changing `DatabaseWrapper` core connection methods
- Modifying `ConfigManager._loadConfig()` or `_mergeConfigs()`
- Changing `TheBot.sendMessage()` signature
- Modifying `HandlersManager._processMessageRec()`
- Changing any TypedDict structure in `internal/database/models.py`
- Changing `HandlerResultStatus` enum values

---

## 3. Design Patterns

### 3.1 Service-Oriented Architecture

Three-layer structure:
- **Bot Layer**: [`internal/bot/`](../../internal/bot/) — Multi-platform handlers and managers
- **Service Layer**: [`internal/services/`](../../internal/services/) — Cache, queue, LLM, storage
- **Library Layer**: [`lib/`](../../lib/) — Reusable components (AI, markdown, APIs, filters)

### 3.2 Database Patterns

- **Migration System**: Auto-discovery with version tracking from `versions/` directory
- **TypedDict Models**: Runtime validation for all database operations
- **Transaction Safety**: Automatic rollback on failures

### 3.3 Memory Optimization

- Use `__slots__` for all data classes and models
- Singleton services: Cache and queue services use singleton pattern
- Namespace organization: Logical separation with persistence options

### 3.4 API Integration Standards

- **Rate Limiting**: Sliding window algorithm with per-service limits
- **Caching Strategy**: TTL-based with namespace organization
- **Error Handling**: Proper timeout and retry mechanisms
- **Golden Testing**: Deterministic testing without API quotas

### 3.5 Migration Documentation Protocol

**Critical lesson from migration_009 error, dood!**

When creating or modifying database migrations, ALWAYS:

1. **Read ALL Existing Migrations First**
   - Never assume what migrations do from their names
   - Read the actual migration code for all relevant migrations
   ```bash
   ls internal/database/migrations/versions/
   # Then read each migration file to understand its purpose
   ```

2. **Verify Migration Functionality**
   - Check what columns/tables each migration actually adds/removes
   - Cross-reference with existing documentation
   - Identify any gaps or inconsistencies in current docs

3. **Document Only Actual Changes**
   - Each migration should only document what IT does
   - Never mix functionality from different migrations
   - Preserve complete migration history timeline

4. **Validate Documentation Changes**
   - Review all migrations mentioned in docs still exist
   - Ensure no migrations are accidentally omitted
   - Verify column attributions match actual migration code

5. **Update Both Human and LLM Documentation**
   - Update `docs/database-schema.md` AND `docs/database-schema-llm.md`
   - Add migration entry to the migrations list with description
   - Update affected table schemas with new columns
   - Update example queries if column affects common operations

### 3.6 Migration Versioning Protocol

**Critical lesson from migration version conflict, dood!**

**Mandatory Migration Creation Protocol:**

1. **ALWAYS Check Existing Migrations First**
   ```bash
   ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
   # This shows the highest numbered migration file
   ```

2. **Version Calculation Rule:**
   ```
   New Migration Version = Latest Migration Version + 1
   ```
   Example: If highest is `migration_008`, create `migration_009`

3. **Never assume the next version** — always list the directory first

---

## See Also

- [`index.md`](index.md) — Project overview, mandatory rules, project map
- [`handlers.md`](handlers.md) — Handler system details and creation guide
- [`database.md`](database.md) — Database operations, migrations, multi-source routing
- [`services.md`](services.md) — Service integration patterns (Cache, Queue, LLM, Storage)
- [`configuration.md`](configuration.md) — TOML configuration reference
- [`tasks.md`](tasks.md) — Step-by-step common task workflows

---

*This guide is auto-maintained and should be updated whenever significant architectural changes are made, dood!*  
*Last updated: 2026-04-18, dood!*
