# Gromozeka — Common Tasks & Anti-Patterns

> **Audience:** LLM agents, dood!  
> **Purpose:** Step-by-step decision trees for common tasks and anti-pattern reference, dood!  
> **Self-contained:** Everything needed for task guidance is here, dood!

---

## Table of Contents

1. [Common Task Decision Trees](#1-common-task-decision-trees)
2. [Anti-Patterns — NEVER Do These](#2-anti-patterns--never-do-these)
3. [Subtle Gotchas](#3-subtle-gotchas)

---

## 1. Common Task Decision Trees

### 1.1 "I need to add a new bot command"

```
START
├── Is this command related to an existing handler's responsibility?
│   ├── YES → Add @commandHandlerV2 method to that handler
│   │         Follow handlers.md Section 4 decorator pattern
│   │         Run: make format lint && make test
│   │         DONE
│   └── NO → Create new handler file
│             ↓
│         Does the command need:
│         ├── LLM generation? → Use self.llmService.generateText() in handler
│         ├── DB storage? → Use self.db.* methods
│         ├── Caching? → Use self.cache.* methods
│         └── External API? → Add new lib or reuse existing
│             ↓
│         Register handler in HandlersManager (manager.py:249)
│         Write tests in tests/bot/
│         Run: make format lint && make test
│         DONE
```

**Reference docs:**
- [`handlers.md`](handlers.md) — full handler creation guide
- [`services.md`](services.md) — service usage patterns

---

### 1.2 "I need to add a new API integration"

```
START
├── Step 1: Create lib/<service-name>/ directory
│         - client.py: async HTTP client class
│         - models.py: response model TypedDicts
│         - README.md: usage documentation
│         - test_client.py: client tests
│
├── Step 2: Add config section to ConfigManager
│         - Add getter method to internal/config/manager.py
│         - Add default TOML keys to configs/00-defaults/
│
├── Step 3: Create handler using the new lib
│         - Create internal/bot/common/handlers/my_service.py
│         - Import lib client inside handler
│         - Check enabled flag from configManager
│         - Register conditionally in HandlersManager (like WeatherHandler)
│
└── Step 4: Tests
          - tests/lib_my_service/ for client tests (with golden data)
          - tests/bot/ for handler tests
          - Run: make format lint && make test
          DONE
```

**Reference docs:**
- [`libraries.md`](libraries.md) — existing lib patterns to follow
- [`configuration.md`](configuration.md) — adding config sections
- [`handlers.md`](handlers.md) — conditional handler registration
- [`testing.md`](testing.md) — golden data testing

---

### 1.3 "I need to modify the database schema"

```
START
├── Step 1: Check highest existing migration version
│         Run: ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
│
├── Step 2: Create migration file
│         Path: internal/database/migrations/versions/NNN_description.py
│         Class: MigrationNNNDescription(BaseMigration)
│         Implement: up(cursor), down(cursor)
│         Set: version = NNN (next sequential number)
│
├── Step 3: Register migration
│         In internal/database migrations registry or __init__.py
│
├── Step 4: Add DatabaseWrapper methods
│         In internal/database/wrapper.py
│         Follow existing patterns with self._getConnection()
│
├── Step 5: Update models if needed
│         In internal/database/models.py
│         Add new TypedDict or enum values
│
├── Step 6: Update cache if needed
│         If frequently accessed data: add cache layer in CacheService
│
├── Step 7: Update documentation (CRITICAL, dood!)
│         Update docs/database-schema.md AND docs/database-schema-llm.md
│         Add migration entry with description
│         Update affected table schemas
│
└── Step 8: Tests
          - tests/test_db_wrapper.py
          - internal/database/migrations/test_migrations.py
          - Run: make format lint && make test
          DONE
```

**Reference docs:**
- [`database.md`](database.md) — full migration guide with checklist

---

### 1.4 "I need to add a new LLM provider"

```
START
├── Step 1: Create provider file
│         Path: lib/ai/providers/my_provider.py
│         Class: MyProvider(AbstractLLMProvider)
│         Must implement: _createModel(modelConfig) -> AbstractModel
│
├── Step 2: Create model class (if needed)
│         In same file or separate
│         Class: MyModel(AbstractModel)
│         Must implement: _generateText(messages, tools) -> ModelRunResult
│
├── Step 3: Register provider type in LLMManager
│         File: lib/ai/manager.py:40
│         Add to providerTypes dict: {"my-provider": MyProvider}
│
├── Step 4: Add config example
│         In configs/00-defaults/ or docs
│         [models.providers.my-provider-name]
│         type = "my-provider"
│         api-key = "${MY_PROVIDER_API_KEY}"
│
└── Step 5: Tests
          Path: lib/ai/providers/test_my_provider.py
          Run: make format lint && make test
          DONE
```

**Reference docs:**
- [`libraries.md`](libraries.md) — lib/ai API reference
- [`configuration.md`](configuration.md) — `[models]` TOML config

---

### 1.5 "I need to fix a bug in a handler"

```
START
├── Step 1: Identify the handler
│         Look at handler list in handlers.md Section 1
│         Find the relevant file
│
├── Step 2: Check if bug is in:
│   ├── newMessageHandler() → Fix logic, return correct HandlerResultStatus
│   ├── A command method → Fix the @commandHandlerV2 decorated method
│   ├── A helper called by handler → Fix the helper
│   └── A service used by handler → Fix the service (separate task)
│
├── Step 3: Write regression test FIRST
│         in tests/bot/test_<handler_name>.py
│         Test should FAIL before fix
│
├── Step 4: Fix the bug
│         Apply minimal change
│         Test should now PASS
│
├── Step 5: Verify no regressions
│         Run: make format lint && make test
│         DONE
```

**Reference docs:**
- [`handlers.md`](handlers.md) — handler patterns and `HandlerResultStatus`
- [`testing.md`](testing.md) — writing handler tests

---

### 1.6 "I need to modify a service"

```
START
├── Step 1: Read the service file
│         Understand the singleton pattern and existing API
│
├── Step 2: Identify modification type:
│   ├── Add new method → Add with docstring, type hints, tests
│   ├── Modify existing method → Check all callers first!
│   └── Change data structure → May break all callers — audit first
│
├── Step 3: Preserve singleton pattern
│         - Keep _instance, _lock, __new__, __init__ with hasattr guard
│         - Keep getInstance() classmethod
│         - Keep thread-safe initialization
│
└── Step 4: Quality checks
          - All new methods have docstrings and type hints
          - Tests updated in tests/services/
          - Run: make format lint && make test
          DONE
```

**Reference docs:**
- [`services.md`](services.md) — service singleton pattern
- [`architecture.md`](architecture.md) — ADR-001 (singleton services)

---

## 2. Anti-Patterns — NEVER Do These

### ❌ Direct singleton construction
```python
# WRONG — creates second instance with empty state, dood!
cache = CacheService()

# CORRECT, dood!
cache = CacheService.getInstance()
```

### ❌ Calling platform APIs directly from handlers
```python
# WRONG — tightly couples handler to Telegram, dood!
await self.tgBot.send_message(...)

# CORRECT — use BaseBotHandler's sendMessage, dood!
await self.sendMessage(ensuredMessage, messageText="...", messageCategory=MessageCategory.BOT)
```

### ❌ Adding `LLMMessageHandler` before the last position
```python
# WRONG — LLMMessageHandler MUST be last, dood!
self.handlers = [
    (LLMMessageHandler(...), HandlerParallelism.SEQUENTIAL),  # DON'T!
    (MyHandler(...), HandlerParallelism.PARALLEL),
]

# CORRECT, dood!
self.handlers = [
    (MyHandler(...), HandlerParallelism.PARALLEL),
    (LLMMessageHandler(...), HandlerParallelism.SEQUENTIAL),  # Always last!
]
```

### ❌ Using `cd` to change into subdirectory
```bash
# WRONG, dood!
cd internal && python test.py

# CORRECT, dood!
./venv/bin/python3 internal/test.py
```

### ❌ Missing docstrings
```python
# WRONG — no docstring, dood!
def getChatSettings(self, chatId: int) -> ChatSettingsDict:
    return self.cache.get(chatId)

# CORRECT, dood!
def getChatSettings(self, chatId: int) -> ChatSettingsDict:
    """Get chat settings from cache, dood!

    Args:
        chatId: Chat identifier

    Returns:
        ChatSettingsDict with all settings
    """
    return self.cache.get(chatId)
```

### ❌ Using snake_case for variables/functions
```python
# WRONG — snake_case is not allowed for variables/functions, dood!
chat_settings = getChatSettings()
def get_chat_settings():
    ...

# CORRECT — camelCase, dood!
chatSettings = getChatSettings()
def getChatSettings():
    ...
```

### ❌ Using camelCase for constants
```python
# WRONG, dood!
defaultThreadId = 0

# CORRECT, dood!
DEFAULT_THREAD_ID: int = 0
```

### ❌ Skipping `make format lint` before committing
```bash
# WRONG workflow, dood!
# Edit file → git commit

# CORRECT workflow, dood!
# Edit file → make format lint → make test → git commit
```

### ❌ Not resetting singletons in tests
```python
# WRONG — may carry state from previous test, dood!
def testSomething():
    service = LLMService.getInstance()
    ...

# CORRECT — use the autouse fixture or reset manually, dood!
@pytest.fixture(autouse=True)
def resetSingleton():
    """Reset singleton for clean test state, dood!"""
    LLMService._instance = None
    yield
    LLMService._instance = None
```

### ❌ Returning wrong `HandlerResultStatus`
```python
# WRONG — FINAL stops the chain; if other handlers should run, dood!
return HandlerResultStatus.FINAL  # Stops all subsequent handlers

# CORRECT — if other handlers should still process, dood!
return HandlerResultStatus.SKIPPED  # Let others handle it
return HandlerResultStatus.NEXT     # I processed it, but continue
```

### ❌ Forgetting to check if feature is enabled in config
```python
# WRONG — handler always active even when disabled, dood!
class WeatherHandler(BaseBotHandler):
    ...  # No enabled check

# CORRECT — conditional registration in HandlersManager, dood!
if self.configManager.getOpenWeatherMapConfig().get("enabled", False):
    self.handlers.append(
        (WeatherHandler(configManager, database, llmManager, botProvider), HandlerParallelism.PARALLEL)
    )
```

### ❌ Not using `Optional` type for nullable values
```python
# WRONG, dood!
def getChatInfo(self, chatId: int) -> ChatInfoDict:
    ...  # may return None!

# CORRECT, dood!
def getChatInfo(self, chatId: int) -> Optional[ChatInfoDict]:
    ...
```

### ❌ Creating migration with wrong version number
```bash
# WRONG — assuming version without checking, dood!
# Just created migration_005.py without checking existing migrations

# CORRECT — always check first, dood!
ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
# Then use: latest_version + 1
```

---

## 3. Subtle Gotchas

| Gotcha | Description | Solution |
|---|---|---|
| `MessageIdType` is `Union[int, str]` | Telegram uses `int` IDs, Max uses `str` IDs | Always use `MessageIdType` type, cast when needed |
| `chatId` sign determines chat type | Positive = private, negative = group | Use `ChatType.PRIVATE if chatId > 0 else ChatType.GROUP` |
| `DEFAULT_THREAD_ID = 0` | Default thread uses ID 0 (not None) in DB | Never use `None` for thread ID in DB queries |
| Config merge is recursive | Nested dicts are merged, not replaced | Be careful with deep config overrides |
| `LLMService.initialized` guard | Singleton init runs once via `hasattr` check | Never check `initialized` directly in new code |
| Max platform sticker stubs | Animated stickers have stub URLs, not real images | Check `url.startswith(...)` before processing |
| Thread-safe LRU cache uses `RLock` | `CacheService` internal `LRUCache` is thread-safe | Don't bypass with direct dict access |
| `bot_owners` can be username OR int ID | Both are valid in config | Handle both types in owner checks |
| `EnsuredMessage.threadId` may be `None` | Not all messages are in threads | Always handle `None` threadId |
| `condenseThread` default is `True` | Context is condensed by default | Pass `condenseThread=False` if you need full history |
| `getChatSettings()` returns tuples | Returns `Dict[str, tuple[str, int]]` — value + updated_by | Use `settings[key][0]` to get just the value |
| `setChatSetting` requires `updatedBy` | `updatedBy` is keyword-only, required argument | Always pass `updatedBy=userId` when calling |
| `mediaGroupDelaySecs` default is 5.0 | Time-based Telegram media group detection | Adjust per job if source chat uploads slowly |

---

## See Also

- [`index.md`](index.md) — Project overview, mandatory rules, critical commands
- [`architecture.md`](architecture.md) — ADRs explaining why things work the way they do
- [`handlers.md`](handlers.md) — Detailed handler creation and registration guide
- [`database.md`](database.md) — Database operations and migration guide
- [`services.md`](services.md) — Service integration patterns
- [`libraries.md`](libraries.md) — Library API reference
- [`configuration.md`](configuration.md) — Configuration section reference
- [`testing.md`](testing.md) — Testing patterns and fixtures

---

*This guide is auto-maintained and should be updated whenever new patterns or gotchas are discovered, dood!*  
*Last updated: 2026-04-18, dood!*
