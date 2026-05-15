# Gromozeka — Common Tasks & Anti-Patterns

> **Audience:** LLM agents  
> **Purpose:** Step-by-step decision trees for common tasks and anti-pattern reference  
> **Self-contained:** Everything needed for task guidance is here

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
- **Custom handlers:** See [`custom-modules-design.md`](../../custom-modules-design.md) for loading handlers via TOML configuration without code changes

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
│         Implement:
│             async def up(self, sqlProvider: BaseSQLProvider) -> None
│             async def down(self, sqlProvider: BaseSQLProvider) -> None
│         Export: def getMigration() -> Type[BaseMigration]
│         Set: version: int = NNN (next sequential number)
│         Follow SQL portability rules — no AUTOINCREMENT,
│           no DEFAULT CURRENT_TIMESTAMP, no COLLATE NOCASE, no SERIAL,
│           use :named placeholders, portable types only.
│           See docs/sql-portability-guide.md for the full ruleset.
│
├── Step 3: Add Database methods
│         In internal/database/ (Database class or relevant repository submodule)
│         Go through BaseSQLProvider helpers:
│           execute / executeFetchOne / executeFetchAll / batchExecute / upsert
│         Use :named placeholders and provider.applyPagination /
│         provider.getCaseInsensitiveComparison for portability.
│         Do NOT use raw sqlite3 calls or self._getConnection().
│
├── Step 4: Update models if needed
│         In internal/database/models.py
│         Add new TypedDict or enum values
│
├── Step 5: Update cache if needed
│         If frequently accessed data: add cache layer in CacheService
│
├── Step 6: Update documentation (CRITICAL)
│         Update all three schema docs in sync:
│           - docs/database-schema.md (human-oriented)
│           - docs/database-schema-llm.md (LLM-oriented)
│           - docs/llm/database.md (migration pattern + version list)
│         Add migration entry with description.
│         Update affected table schemas.
│
└── Step 7: Tests
          - tests/test_db_wrapper.py
          - internal/database/migrations/test_migrations.py
          - Run: make format lint && make test
          DONE
```

**Reference docs:**
- [`database.md`](database.md) — full migration guide with checklist
- [`../sql-portability-guide.md`](../sql-portability-guide.md) — cross-RDBMS SQL rules
- [`.agents/skills/add-database-migration/SKILL.md`](../../.agents/skills/add-database-migration/SKILL.md) — loadable skill with scaffolding template

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

> **Rule:** For any bug fix — production code, test code, config, or docs — write a
> regression test that FAILS before the fix and PASSES after. Include edge-case
> tests that the bug touched (Optional/Union conversions, None handling, schema
> mismatches, etc.). Never rely on existing coverage alone.

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
└── Step 5: Verify no regressions
          Run: make format lint && make test
          DONE
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

### 1.7 "I need to debug or replay an LLM conversation"

Two complementary tools exist for replaying LLM interactions outside the normal chat flow:

**Bot command** (with tools): `/llm_replay <model_name>` in `DevCommandsHandler`
- Attach a JSON log file and specify a model name
- Replays through `LLMService.generateTextViaLLM()` with all registered tools active
- Streams intermediate results and reports a summary
- See [`handlers.md`](handlers.md) -- DevCommandsHandler section for details

**CLI script** (without tools): `scripts/run_llm_debug_query.py`
- Runs a replay from the command line with no bot/tool context
- Shares the `reconstructMessages()` utility with the bot command (from `internal/services/llm/utils.py`)

**Conversion script**: `scripts/convert_readable_to_llm_log.py`
- Converts human-readable YAML LLM logs back to the JSON format expected by both replay tools

**Typical workflow:**
1. Export or capture an LLM log (JSON or readable YAML)
2. If YAML: convert with `./venv/bin/python3 scripts/convert_readable_to_llm_log.py`
3. Replay via `/llm_replay` (in-chat, with tools) or `run_llm_debug_query.py` (CLI, no tools)

**Reference docs:**
- [`handlers.md`](handlers.md) -- `/llm_replay` command documentation
- [`services.md`](services.md) -- `internal/services/llm/utils.py` utility reference

---

## 2. Anti-Patterns — NEVER Do These

### ❌ Direct singleton construction
```python
# WRONG — creates second instance with empty state
cache = CacheService()

# CORRECT
cache = CacheService.getInstance()
```

### ❌ Calling platform APIs directly from handlers
```python
# WRONG — tightly couples handler to Telegram
await self.tgBot.send_message(...)

# CORRECT — use BaseBotHandler's sendMessage
await self.sendMessage(ensuredMessage, messageText="...", messageCategory=MessageCategory.BOT)
```

### ❌ Adding `LLMMessageHandler` before the last position
```python
# WRONG — LLMMessageHandler MUST be last
self.handlers = [
    (LLMMessageHandler(...), HandlerParallelism.SEQUENTIAL),  # DON'T!
    (MyHandler(...), HandlerParallelism.PARALLEL),
]

# CORRECT
self.handlers = [
    (MyHandler(...), HandlerParallelism.PARALLEL),
    (LLMMessageHandler(...), HandlerParallelism.SEQUENTIAL),  # Always last!
]
```

### ❌ Using `cd` to change into subdirectory
```bash
# WRONG
cd internal && python test.py

# CORRECT
./venv/bin/python3 internal/test.py
```

### ❌ Missing docstrings
```python
# WRONG — no docstring
def getChatSettings(self, chatId: int) -> ChatSettingsDict:
    return self.cache.get(chatId)

# CORRECT
def getChatSettings(self, chatId: int) -> ChatSettingsDict:
    """Get chat settings from cache

    Args:
        chatId: Chat identifier

    Returns:
        ChatSettingsDict with all settings
    """
    return self.cache.get(chatId)
```

### ❌ Using snake_case for variables/functions
```python
# WRONG — snake_case is not allowed for variables/functions
chat_settings = getChatSettings()
def get_chat_settings():
    ...

# CORRECT — camelCase
chatSettings = getChatSettings()
def getChatSettings():
    ...
```

### ❌ Using camelCase for constants
```python
# WRONG
defaultThreadId = 0

# CORRECT
DEFAULT_THREAD_ID: int = 0
```

### ❌ Skipping `make format lint` before committing
```bash
# WRONG workflow
# Edit file → git commit

# CORRECT workflow
# Edit file → make format lint → make test → git commit
```

### ❌ Not resetting singletons in tests
```python
# WRONG — may carry state from previous test
def testSomething():
    service = LLMService.getInstance()
    ...

# CORRECT — use the autouse fixture or reset manually
@pytest.fixture(autouse=True)
def resetSingleton():
    """Reset singleton for clean test state"""
    LLMService._instance = None
    yield
    LLMService._instance = None
```

### ❌ Returning wrong `HandlerResultStatus`
```python
# WRONG — FINAL stops the chain; if other handlers should run
return HandlerResultStatus.FINAL  # Stops all subsequent handlers

# CORRECT — if other handlers should still process
return HandlerResultStatus.SKIPPED  # Let others handle it
return HandlerResultStatus.NEXT     # I processed it, but continue
```

### ❌ Forgetting to check if feature is enabled in config
```python
# WRONG — handler always active even when disabled
class WeatherHandler(BaseBotHandler):
    ...  # No enabled check

# CORRECT — conditional registration in HandlersManager
if self.configManager.getOpenWeatherMapConfig().get("enabled", False):
    self.handlers.append(
        (WeatherHandler(configManager=configManager, database=database, botProvider=botProvider), HandlerParallelism.PARALLEL)
    )
```

### ❌ Not using `Optional` type for nullable values
```python
# WRONG
def getChatInfo(self, chatId: int) -> ChatInfoDict:
    ...  # may return None!

# CORRECT
def getChatInfo(self, chatId: int) -> Optional[ChatInfoDict]:
    ...
```

### ❌ Creating migration with wrong version number
```bash
# WRONG — assuming version without checking
# Just created migration_005.py without checking existing migrations

# CORRECT — always check first
ls -1 internal/database/migrations/versions/ | grep "migration_" | sort -V | tail -1
# Then use: latest_version + 1
```

---

## 3. Subtle Gotchas

| Gotcha | Description | Solution |
|---|---|---|
| `MessageId` class wraps `int\|str` | Telegram uses `int` IDs, Max uses `str` IDs | Always use `MessageId` class; use `.asInt()` for Telegram, `.asStr()` for Max/SQL |
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
| `MessageSender.name` (NOT `displayName`) | The sender's display name lives on `.name`, not `.displayName` | Use `ensuredMessage.messageSender.name` |
| `MediaStatus` / `MessageType` are enums | They are NOT plain strings — use the enum members | `MediaStatus.DONE`, `MessageType.IMAGE` (don't pass `"done"` / `"image"`) |
| `LLMService.registerTool` is flat-args | No nested config object — pass tool name, schema, callback, etc. as kwargs | See `DivinationHandler` registration site for an example |
| `random.SystemRandom()` for non-deterministic draws | New convention introduced by [`lib/divination/drawing.py`](../../lib/divination/drawing.py) — prefer `random.SystemRandom()` for security/unpredictability | Tests inject a seeded `random.Random` for reproducibility instead of monkeypatching `random` |
| Layout discovery negative cache | Failed discoveries stored as `name_en=''`, `n_symbols=0` in `divination_layouts` table | Prevents repeated failed attempts, check with `isNegativeCacheEntry()` |
| `getLikeComparison()` for fuzzy search | Provider method for case-insensitive LIKE pattern matching | Use in `divinationLayouts.getLayout()` for fuzzy layout name search |
| `getCaseInsensitiveComparison()` for exact matches | Provider method for case-insensitive exact match | Use for username/email lookups, chat settings keys |
| Schema requirements for structured output | OpenAI strict mode: all properties required, `additionalProperties: false`, no root `oneOf`/`anyOf` | See tasks.md §4.5 for complete rules and example |
| `sqlToCustomType()` handles `Optional[T]` | Returns `(True, None)` for `Optional[...]` when data is `None` | Properly unwraps Union types and handles `None` values for nullable columns |

---

## 4. Lessons Learned & Common Pitfalls

This section captures real issues encountered during implementation to help you avoid them in the future.

### 4.1 Chat Settings Registration (CRITICAL)

When adding new `ChatSettingsKey` enum values, you **must** also add corresponding entries to the `_chatSettingsInfo` dictionary. Without these entries, users cannot configure the settings in the bot.

**What you need to do:**

```python
# 1. Add enum value to ChatSettingsKey (StrEnum; string value is kebab-case
#    and must match the TOML default key exactly)
class ChatSettingsKey(StrEnum):
    YOUR_NEW_SETTING = "your-new-setting"
    """Short code-level description of the setting."""

# 2. Add entry to _chatSettingsInfo dictionary in same file.
#    The value type is ChatSettingsInfoValue — a TypedDict, so entries are
#    dict literals, NOT dataclass-style constructor calls.
_chatSettingsInfo: Dict[ChatSettingsKey, ChatSettingsInfoValue] = {
    # ... existing entries ...
    ChatSettingsKey.YOUR_NEW_SETTING: {
        "type": ChatSettingsType.STRING,           # or MODEL, BOOL, INT, FLOAT, IMAGE_MODEL
        "short": "Короткое описание на русском",    # shown in /settings list
        "long": "Длинное описание на русском",     # shown when editing
        "page": ChatSettingsPage.BOT_OWNER_SYSTEM,  # which settings page
    },
}
```

> **Convention:** `UPPER_CASE` Python name ↔ `kebab-case` string value ↔ `kebab-case` TOML key. All three must match. Do not use underscores in the string value or TOML key.

**Requirement for Default Values:**

After adding entries to `_chatSettingsInfo`, you **MUST** also add default values to the appropriate config file (typically `configs/00-defaults/bot-defaults.toml` for bot settings).

**Without default values:**
- The settings will exist but have no actual content/prompts
- Users cannot use the feature until defaults are provided
- The `/settings` command will show the setting but it will be empty

**Example of forgetting defaults (BAD):**

```bash
# You add the ChatSettingsKey and _chatSettingsInfo entries...
$ /settings divination-discovery-info-prompt
# Setting name: divination-discovery-info-prompt
# Short: Discover divination layouts via web search
# Long: Allows dynamic discovery of custom layouts using AI
# Current value: [EMPTY - no default configured!]
# User tries to use the feature... ERROR: No prompt available
```

**Example of including defaults (GOOD):**

```bash
# User runs /settings and sees:
# Setting name: divination-discovery-info-prompt
# Short: Discover divination layouts via web search
# Long: Allows dynamic discovery of custom layouts using AI
# Current value: "I need information about a {systemId}..."
# User tries the feature... SUCCESS! It works immediately
```

**How to add default values:**

The default values should:
- Match the key names from `ChatSettingsKey` (using kebab-case: `DIVINATION_DISCOVERY_INFO_PROMPT` → `divination-discovery-info-prompt`)
- Be placed in the appropriate config file based on the `page` field
- Use proper TOML syntax with triple quotes for multi-line strings
- Include placeholders in format `{placeholderName}` if the prompt uses them

```toml
# In configs/00-defaults/bot-defaults.toml
[bot.defaults]
# ... existing settings ...

your-new-setting = """
This is the default value for your new setting.
Use triple quotes for multi-line content.
Include placeholders like {userName} if needed.
"""

divination-discovery-info-prompt = """
I need information about a {systemId} divination layout called "{layoutName}".
The user wants to use this layout for a reading, but it's not in my predefined list.

Use the web_search tool to find information about this layout. Look for:
1. What is the name of this layout?
2. How many cards/runes are drawn in it?
3. What are the positions? For each position, describe:
   - The name of the position (usually in English)
   - What this position represents or asks about

Search for authoritative sources on {systemId} layouts, books, or websites that describe this specific spread.
Return a detailed description of the layout including all position meanings.
"""
```

**Why this matters:**
- The `_chatSettingsInfo` dictionary provides metadata for the `/settings` command
- Default values provide the actual content/prompts that make settings functional
- Without entries, your settings won't appear in `/settings` output
- Without defaults, settings appear but are empty/non-functional
- Users won't be able to use your new feature at all without defaults
- The bot throws errors when trying to display unrecognized settings

**Where to find this:**
- Look at `internal/bot/models/chat_settings.py` for the full pattern
- Examine existing entries to understand the metadata structure
- Check `configs/00-defaults/bot-defaults.toml` for default value examples
- Load the [`add-chat-setting`](../../.agents/skills/add-chat-setting/SKILL.md) skill for a step-by-step recipe covering all four required sites and the `getChatSettings()` tuple-return gotcha

---

### 4.2 Import Placement (CRITICAL)

**NEVER** place imports inside methods or functions unless absolutely unavoidable (even for cyclic dependencies). All imports must be at the top of the file.

**Common mistake to avoid:**

```python
# WRONG — imports inside method (anti-pattern!)
class MyClass:
    def someMethod(self):
        import json  # This should be at the top!
        from datetime import datetime  # So should this!
        ...
```

**Correct pattern:**

```python
# CORRECT — all imports at the top
import json
from datetime import datetime
from typing import Optional

class MyClass:
    def someMethod(self):
        # Use the already-imported modules
        data = json.loads(...)
        now = datetime.now()
        ...
```

**After adding imports, always run:**

```bash
make format
```

This runs `isort` to properly organize imports according to the project's style guide. Imports should be sorted into these sections:
1. Standard library imports
2. Third-party imports
3. Local application imports

**Why this matters:**
- Import placement affects code readability and maintainability
- `isort` enforces consistent import ordering across the codebase
- Imports inside methods are harder to discover and maintain
- The `make format` pipeline expects imports to be organized correctly

**Exception note:**
The only valid exception for placing an import inside a method is to resolve a cyclic dependency that cannot be broken by refactoring. This is rare and should be documented with a comment explaining why it was necessary.

---

### 4.3 Code Duplication (Best Practice)

When you find yourself implementing the same logic in multiple places, extract it into a helper method. This makes the code more maintainable and reduces bugs.

**Example of the problem:**

```python
# WRONG — same logic duplicated in two places
class MyHandler(BaseBotHandler):
    async def _handleReadingFromArgs(self, ensuredMessage, args):
        # Layout discovery logic duplicated here
        layout = self._findLayoutByNameOrCode(args[0])

    async def _runReadingForTool(self, ensuredMessage, args):
        # Same layout discovery logic duplicated here
        layout = self._findLayoutByNameOrCode(args[0])
```

**Correct approach:**

```python
# CORRECT — extracted into a helper method
class MyHandler(BaseBotHandler):
    async def _discoverLayout(
        self,
        layoutIdentifier: str
    ) -> Optional[Layout]:
        """Discover layout by name or code.

        Args:
            layoutIdentifier: Layout name or code to search for

        Returns:
            Layout object if found, None otherwise
        """
        # Single implementation
        return self._findLayoutByNameOrCode(layoutIdentifier)

    async def _handleReadingFromArgs(self, ensuredMessage, args):
        layout = await self._discoverLayout(args[0])

    async def _runReadingForTool(self, ensuredMessage, args):
        layout = await self._discoverLayout(args[0])
```

**Why this matters:**
- Single source of truth for the logic
- Easier to maintain — fix once, applies everywhere
- Reduces chance of subtle differences between copies
- Makes testing easier — test one method, not multiple locations
- When debugging, you only need to trace through one implementation

**When to extract:**
- Logic appears 2+ times
- The logic is more than 1-2 lines
- The logic has any complexity (if statements, error handling, etc.)

---

### 4.4 Type Safety in Tests (Testing)

When mocking objects like `EnsuredMessage`, use the actual class types rather than plain dictionaries. This prevents type-related bugs and ensures tests catch real issues.

**Common mistake to avoid:**

```python
# WRONG — using dict instead of actual class type
def test_ReadingHandler():
    # Type: dict, not EnsuredMessage
    mockMessage = {
        "messageId": 123,
        "messageText": "/taro",
        "chatId": 456,
    }
    # May pass type check but fail at runtime with missing fields
```

**Correct approach:**

```python
# CORRECT — using actual class types
from internal.bot.models import EnsuredMessage

def test_ReadingHandler():
    mockMessage = EnsuredMessage(
        messageId=MessageId(123),  # MessageId wrapping int (Telegram uses int)
        messageText="/taro",
        chatId=456,  # Type: int
        messageSender=MessageSender(id=789, isBot=False,
        timestamp=datetime.now(),
    )
```

**Why this matters:**
- Type checkers (pyright) can verify all required fields are present
- Tests catch type errors that would occur in production
- Mock objects match the actual API shape
- Prevents runtime errors from missing or incorrectly-typed fields
- Makes refactoring safer — if `EnsuredMessage` changes, test errors will show you what to update

**Implementation tips:**
- Use pytest fixtures for commonly-used mock objects
- Check `tests/conftest.py` for existing fixtures like `mockMessage`
- Use `mocker.Mock` for methods, but keep the object type correct
- Always import types from their actual modules, don't redefine them in tests

---

### 4.5 Strict JSON Schema Format for Structured Output

When using `LLMService.generateStructured()`, the `schema` parameter must be a **strict JSON Schema** — not Python type hints, classes, or TypedDict. OpenAI's structured outputs and some other providers enforce strict validation and will reject schemas that don't follow this format.

**Common mistake to avoid:**

```python
# WRONG — passing Python types/classes, schema is not valid JSON Schema
from typing import TypedDict

class MyResponse(TypedDict):
    answer: str
    confidence: float

result = await llmService.generateStructured(
    prompt="What is 2+2?",
    schema=MyResponse,  # WRONG! This is not a JSON Schema!
    ...
)

# ALSO WRONG — using Python type names in schema
schema = {
    "type": "object",
    "properties": {
        "answer": {"type": str},       # WRONG! str is a Python type, not a JSON Schema type
        "confidence": {"type": float}, # WRONG! float is Python, not JSON Schema
    },
    # Missing required and additionalProperties fields
}
```

**Correct approach:**

```python
# CORRECT — proper JSON Schema with no optional fields
schema = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},        # JSON Schema type, not str
        "confidence": {"type": "number"},   # JSON Schema type, not float/int
    },
    "required": ["answer", "confidence"],    # ALL fields are required
    "additionalProperties": False,            # No extra fields allowed
}

result = await llmService.generateStructured(
    prompt="What is 2+2?",
    schema=schema,
    chatId=chatId,
    chatSettings=chatSettings,
    modelKey=ChatSettingsKey.CHAT_MODEL,
    fallbackKey=ChatSettingsKey.CHAT_FALLBACK_MODEL,
)

if result.status == ModelResultStatus.FINAL:
    answer = result.data.get("answer")
    confidence = result.data.get("confidence")
```

**Required JSON Schema elements:**

1. **`"type": "object"`** at the top level
2. **`"properties"`** dict containing all field definitions
3. Each property must have a valid JSON Schema type:
   - `"string"` (not `str`)
   - `"number"` (not `float` or `int`)
   - `"integer"` (whole numbers only)
   - `"boolean"` (not `bool`)
   - `"array"` (not `list`)
   - `"object"` (for nested objects)
4. **`"required"`** array listing **ALL fields** — no optional fields allowed
5. **`"additionalProperties": False`** to ensure strict validation

**Why this matters:**

- **OpenAI structured outputs** requires strict JSON Schema format and will reject any schema that doesn't meet these requirements
- **YC OpenAI's native models** (yandexgpt, aliceai-llm, deepseek-v32) enforce this strictly and return HTTP 400 "Invalid JSON Schema: all fields must be required" when violated
- Other providers may have similar validation — using the strict format ensures compatibility across all providers
- Mistakes here result in hard-to-debug API errors rather than clear Python type errors

**Reference implementation:**

See [`scripts/check_structured_output.py`](../../scripts/check_structured_output.py) for the reference implementation. This script probes each configured model with a strictly-formatted schema to verify structured output support. The probe schema (lines 106-114) demonstrates the correct format:

```python
# From scripts/check_structured_output.py — correct strict schema format
_PROBE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["answer", "confidence"],
    "additionalProperties": False,
}
```

**Testing your schemas:**

Before deploying a new schema, you can test it locally:

```bash
# Test structured output with the current configuration
./venv/bin/python3 scripts/check_structured_output.py

# Test only specific providers/models
./venv/bin/python3 scripts/check_structured_output.py --provider yc-openai
./venv/bin/python3 scripts/check_structured_output.py --model "yc-openai/yandexgpt"
```

**Additional notes:**

- Nested objects are supported, but each nested object must also follow the strict format with `required` and `additionalProperties: False`
- Arrays can specify an `items` schema, but the items themselves must follow the same strict rules if they are objects
- If you need optional fields, you must either make them required with a default semantic value (e.g., `null`, empty string) or restructure your schema to handle the logic in code after parsing
- The `strict=True` parameter in `generateStructured()` requests strict enforcement from providers that support it
- Always import `ModelStructuredResult` from `lib.ai` to get proper type hints for the result

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

*This guide is auto-maintained and should be updated whenever new patterns or gotchas are discovered*
*Last updated: 2026-05-15*
