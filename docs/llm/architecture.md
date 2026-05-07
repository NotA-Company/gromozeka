# Gromozeka — Architecture & Design Decisions

> **Audience:** LLM agents  
> **Purpose:** Architecture Decision Records, component dependencies, design patterns  
> **Self-contained:** Everything needed for architecture understanding is here

---

## Table of Contents

1. [Architecture Decision Records](#1-architecture-decision-records)
2. [Dependency Map](#2-dependency-map)
3. [Design Patterns](#3-design-patterns)

---

## 1. Architecture Decision Records

### ADR-001: Singleton Services

**Decision:** `CacheService`, `QueueService`, `LLMService`, `StorageService`, `RateLimiterManager` are all singletons

**Why:** Single instance ensures consistent state across all handlers and avoids duplicate resource usage

**Constraint:** Always use `getInstance()` — never `SomeService()` directly:
```python
# CORRECT
cache = CacheService.getInstance()

# WRONG — creates duplicate state
cache = CacheService()
```

**Thread safety:** All singletons use `RLock` for thread-safe instantiation

**Singleton pattern (MUST preserve when modifying services):**
```python
class MyService:
    """Singleton service"""

    _instance: Optional["MyService"] = None
    _lock: RLock = RLock()

    def __new__(cls) -> "MyService":
        """Create or return singleton instance"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize service once"""
        if hasattr(self, "initialized"):
            return
        self.initialized = True
        # ... actual init ...

    @classmethod
    def getInstance(cls) -> "MyService":
        """Get the singleton instance

        Returns:
            The singleton MyService instance
        """
        return cls()
```

---

### ADR-002: Handler Chain Pattern

**Decision:** Messages flow through an ordered list of `BaseBotHandler` subclasses via [`HandlersManager`](../../internal/bot/common/handlers/manager.py:892)

**Why:** Separation of concerns — each handler does one thing. Easy to add new features without modifying existing handlers

**Chain order (CRITICAL):**
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

**Decision:** [`TheBot`](../../internal/bot/common/bot.py:31) wraps both Telegram and Max Messenger APIs behind a unified interface

**Why:** Handlers don't need to know which platform they're on

**Constraint:** Never call Telegram/Max APIs directly from handlers. Always use `self.sendMessage()`, `self.deleteMessage()`, etc. from `BaseBotHandler`

---

### ADR-004: Multi-Source Database Routing

**Decision:** [`Database`](../../internal/database/database.py) supports multiple database sources with internal routing using repository pattern

**Why:** Allows read replicas, separate databases for different data types, cross-bot data reading

**Architecture Principles:**
- **Repository Pattern**: 12 specialized repositories handle specific data domains (chat_info, chat_messages, chat_settings, chat_users, chat_summarization, cache, spam, user_data, media_attachments, delayed_tasks, common)
- **Simple Priority Routing**: `dataSource` param → `chatId` mapping → default source
- **Readonly Protection**: Sources marked `readonly=True` reject write operations
- **Cross-Bot Communication**: Can read from external bot databases via `dataSource` param
- **SQL Portability**: All SQL is provider-agnostic, supporting SQLite3, PostgreSQL, MySQL, and SQLink

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

**SQL Portability Notes:**
- Migration 013 removed `DEFAULT CURRENT_TIMESTAMP` from all timestamp columns for cross-database compatibility
- All timestamp values are now explicitly set in application code
- Provider abstraction layer (`internal/database/providers/`) handles database-specific SQL dialects
- Supports SQLite3, PostgreSQL, MySQL, and SQLink (SQLite3 over REST) providers

**Repository Structure:**
- `ChatInfoRepository` — Chat metadata and information
- `ChatMessagesRepository` — Message storage and retrieval
- `ChatSettingsRepository` — Chat configuration settings
- `ChatUsersRepository` — User-chat relationships
- `ChatSummarizationRepository` — Chat summarization data
- `CacheRepository` — Cache storage operations
- `SpamRepository` — Spam detection and messages
- `UserDataRepository` — User-specific data
- `MediaAttachmentsRepository` — Media file attachments
- `DelayedTasksRepository` — Scheduled task management
- `CommonRepository` — Shared/common operations
- `BaseRepository` — Abstract base with common functionality

**Implementation Details:**
- `ConnectionManager`: Manages connection pools per data source with thread-safe access
- Backward compatible: Works with legacy single database mode
- Optional `dataSource` parameter: Zero breaking changes
- Repository pattern provides clear separation of concerns and easier testing

---

### ADR-005: LLM Provider Fallback

**Decision:** [`LLMManager`](../../lib/ai/manager.py:17) supports multiple providers with automatic fallback

**Why:** If primary LLM provider fails, automatically falls back to secondary

**Providers:** `yc-openai`, `openrouter`, `yc-sdk`, `custom-openai`.

---

### ADR-006: Command Discovery via Decorators

**Decision:** Commands are discovered via `@commandHandlerV2(...)` decorator on methods

**Why:** Zero-registration — add decorator, command is auto-discovered by `HandlersManager`

**Decorator location:** Imported from `internal.bot.models` as `commandHandlerV2`

---

### ADR-007: Configuration Layering

**Decision:** Config loads from multiple TOML files and merges them in order

**Why:** Separates defaults from environment-specific overrides

**Load order:** `--config` file first, then `--config-dir` files sorted alphabetically

**Merge behavior:** Later files override earlier ones. Nested dicts are merged recursively

---

### ADR-008: Cross-Source Aggregation with Intelligent Deduplication

**Decision:** Cross-source database queries use semantic deduplication keys per method type

**Why:** Prevents duplicates when aggregating data across multiple SQLite sources

**Deduplication Keys Strategy:**
- `getUserChats()`: `(userId, chat_id)` — user-chat relationship uniqueness
- `getAllGroupChats()`: `chat_id` — chat uniqueness
- `getSpamMessages()`: `(chat_id, message_id)` — message uniqueness within chat
- `getCacheStorage()`: `(namespace, key)` — cache entry uniqueness
- `getCacheEntry()`: First match (no deduplication) — performance optimization

**Error Handling:** Continue aggregation on individual source failures with warning logs

---

### ADR-009: Time-Based Media Group Completion Detection

**Decision:** Telegram media groups (albums) use time-based completion detection with configurable delay

**Why:** Telegram sends media groups as separate messages with same `media_group_id` but doesn't indicate when all items have arrived

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

**Decision:** `chat_settings` table includes `updated_by` column (INTEGER NOT NULL) to track which user last modified each setting

**Why:** Required for audit capability — knowing who changed what setting

**Implementation:**
- Migration `migration_010` adds `updated_by` column via table recreation pattern
- Existing data: `updated_by=0` set for all existing rows during migration
- `setChatSetting(chatId, key, value, *, updatedBy: int)` — `updatedBy` is required keyword-only argument

**API Design:**
- `getChatSetting(chatId, setting)` — returns `Optional[str]` (just the value for backward compatibility)
- `getChatSettings(chatId)` — returns `Dict[str, tuple[str, int]]` where tuple is `(value, updated_by)`
- This minimizes breaking changes while providing audit capability

---

### ADR-011: Divination Layout Discovery Pattern

**Decision:** Unknown tarot/runes layouts trigger automatic LLM + web search discovery, cached in `divination_layouts` table with negative cache for failures

**Why:** Allows users to request any layout (not just predefined ones), avoids repeated failed discoveries, and scales to thousands of possible layouts

**Discovery Flow (Multi-Tier Resolution):**

**Tier 1**: Predefined layouts in `lib/divination/layouts.py`
- Fast lookup in `TAROT_LAYOUTS` and `RUNES_LAYOUTS` dicts
- Zero database queries for known layouts

**Tier 2**: Database cache (`divination_layouts` table)
- Composite PK: `(system_id, layout_id)`
- Successful discoveries: Full layout definition cached
- Failed discoveries (negative cache): `name_en=''`, `n_symbols=0` entries prevent retries
- Case-insensitive fuzzy search via `getLikeComparison()` for partial matches

**Tier 3**: LLM + Web Search discovery (if `divination discovery-enabled = true`)
- Call 1: `LLMService.generateText(tools=True)` with web search
  - Prompt: `divination-discovery-info-prompt`
  - System: `divination-discovery-system-prompt`
  - Tool: `web_search` automatically used by LLM
- Call 2: `LLMService.generateStructured(schema)` to parse description
  - Prompt: `divination-discovery-structure-prompt`
  - Schema: Strict JSON Schema with required fields
  - Returns validated dictionary
- Save: Persist to `divination_layouts` cache on success
- Negative cache: On failure, store empty entry with 24-hour implied TTL

**Performance Optimizations:**
- Negative cache prevents spamming LLM for non-existent layouts
- Fuzzy search: `divinationLayouts.getLayout()` tries exact match first, then LIKE pattern
- Case-insensitive search: Uses `getCaseInsensitiveComparison()` for exact, `getLikeComparison()` for fuzzy
- No blocking: Discovery only triggered for unknown layouts, not every request

**Configuration:**
```toml
[divination]
discovery-enabled = true  # Master switch
```

**Chat Settings for Discovery:**
- `divination-discovery-system-prompt` — System instruction (both calls)
- `divination-discovery-info-prompt` — Web search prompt (first call)
- `divination-discovery-structure-prompt` — Structured parsing prompt (second call)

**Repository Pattern:**
```python
from internal.database.repositories import DivinationLayoutsRepository

repo = DivinationLayoutsRepository(db.manager)
layout = await repo.getLayout(systemId='tarot', layoutName='three_card')

# Negative cache check
if repo.isNegativeCacheEntry(layout):
    # Layout doesn't exist, don't retry
    return None

# Save successful discovery
await repo.saveLayout(
    systemId='tarot',
    layoutId='custom_layout',
    nameEn='Custom Layout',
    nameRu='Кастомный расклад',
    nSymbols=3,
    positions=json.dumps([...]),
    description='Custom description'
)

# Save negative cache
await repo.saveNegativeCache(systemId='tarot', layoutId='invalid')
```

---

## 2. Dependency Map

### 2.1 Component Dependency Graph

```
GromozekBot (main.py)
├── ConfigManager (internal/config/manager.py)
├── DatabaseManager (internal/database/manager.py)
│   └── Database (internal/database/database.py)
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
                ├── Database (via self.db)
                ├── LLMManager (via self.llmManager)
                ├── ConfigManager (via self.configManager)
                └── TheBot (internal/bot/common/bot.py) [injected]
                    ├── CacheService.getInstance()
                    └── Platform API (Telegram ExtBot or MaxBotClient)
```

### 2.2 Service Initialization Order (Critical)

Services MUST be initialized in this order:

1. `ConfigManager` — first, everything needs config
2. `DatabaseManager` / `Database` — second, services need DB
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
| [`internal/database/database.py`](../../internal/database/database.py) | All DB operations, all handlers that use `self.db` | `make test` — `tests/integration/test_database_operations.py` |
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

#### Safe (isolated)
- Adding a new repository to `Database` without changing existing repositories
- Adding a new handler file without modifying `manager.py`
- Adding a new config getter to `ConfigManager`
- Adding a new LLM provider to `lib/ai/providers/`
- Adding tests

#### Moderate Risk ()
- Modifying `CacheService` internal data structures
- Changing handler execution order in `HandlersManager`
- Modifying `BaseBotHandler.sendMessage()` signature

#### High Risk (ALWAYS run full `make test`)
- Modifying `BaseBotHandler.__init__()` signature
- Changing `Database` core connection methods or repository interfaces
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

**Critical lesson from migration_009 and migration_012 errors**

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

**Critical lesson from migration version conflict**

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
    Example: If highest is `migration_012`, create `migration_013`

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

*This guide is auto-maintained and should be updated whenever significant architectural changes are made*
*Last updated: 2026-05-02*
