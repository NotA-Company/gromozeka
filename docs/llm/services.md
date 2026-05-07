# Gromozeka — Service Integration Patterns

> **Audience:** LLM agents  
> **Purpose:** Complete reference for using CacheService, QueueService, LLMService, StorageService, and RateLimiterManager  
> **Self-contained:** Everything needed for service integration is here

---

## Table of Contents

1. [CacheService](#1-cacheservice)
2. [QueueService](#2-queueservice)
3. [LLMService](#3-llmservice)
4. [StorageService](#4-storageservice)
5. [RateLimiterManager](#5-ratelimitermanager)
6. [Service Singleton Pattern](#6-service-singleton-pattern)

---

## 1. CacheService

**File:** [`internal/services/cache/service.py:88`](../../internal/services/cache/service.py:88)  
**Import:** `from internal.services.cache import CacheService`

```python
# Get singleton instance
cache = CacheService.getInstance()

# MUST inject database before use (done by HandlersManager)
cache.injectDatabase(dbWrapper)

# Chat settings
chatSettings: ChatSettingsDict = cache.getCachedChatSettings(chatId)
cache.cacheChatSettings(chatId, settings)
cache.setChatSetting(chatId, key, value, userId=user.id)
cache.unsetChatSetting(chatId=chatId, key=key)

# Chat info
chatInfo: Optional[ChatInfoDict] = cache.getChatInfo(chatId)
cache.setChatInfo(chatId, chatInfo)

# Chat admins
admins: Optional[Dict[int, Tuple[str, str]]] = cache.getChatAdmins(chatId)
cache.setChatAdmins(chatId, admins)

# User data
userData = cache.getChatUserData(chatId=chatId, userId=userId)

# Default settings
cache.setDefaultChatSettings(None, defaultSettings)  # Global defaults
cache.setDefaultChatSettings(ChatType.GROUP, groupDefaults)  # Type-specific
cache.setDefaultChatSettings("tier-paid", tierDefaults)  # Tier-specific
```

**Key types from** [`internal/services/cache/types.py`](../../internal/services/cache/types.py):
- `HCChatCacheDict` — per-chat cache
- `HCChatUserCacheDict` — per-user-in-chat cache
- `UserDataType` / `UserDataValueType` — user data structures

**IMPORTANT:** `CacheService.injectDatabase(db)` MUST be called before any cache operations. This is done automatically by `HandlersManager`, so only call it manually in tests

---

## 2. QueueService

**File:** [`internal/services/queue_service/service.py:49`](../../internal/services/queue_service/service.py:49)  
**Import:** `from internal.services.queue_service import QueueService, makeEmptyAsyncTask`

```python
queue = QueueService.getInstance()

# Add background task (fire-and-forget)
parseTask = asyncio.create_task(some_coroutine())
await queue.addBackgroundTask(parseTask)

# Add delayed task (runs at specific time)
await queue.addDelayedTask(
    delayedUntil=time.time() + 3600,
    function=DelayedTaskFunction.SEND_MESSAGE,
    kwargs={"chat_id": 123, "text": "Hello"}
)

# Register a handler for delayed tasks
queue.registerDelayedTaskHandler(DelayedTaskFunction.CRON_JOB, my_handler_fn)

# Create empty/no-op task
emptyTask: asyncio.Task = makeEmptyAsyncTask()
```

**`DelayedTaskFunction` enum** (from `internal/services/queue_service/types.py`):
- `CRON_JOB` — periodic cron tasks
- `DO_EXIT` — cleanup on exit
- `SEND_MESSAGE` — scheduled message sending

---

## 3. LLMService

**File:** [`internal/services/llm/service.py:37`](../../internal/services/llm/service.py:37)  
**Import:** `from internal.services.llm import LLMService`

```python
llmService = LLMService.getInstance()

# Generate text response
result: ModelRunResult = await llmService.generateText(
    messages,                    # List[ModelMessage]
    chatId=chatId,
    chatSettings=chatSettings,
    llmManager=self.llmManager,
    modelKey=ChatSettingsKey.CHAT_MODEL,
    fallbackKey=ChatSettingsKey.CHAT_FALLBACK_MODEL,
)

if result.status == ModelResultStatus.FINAL:
    responseText = result.resultText

# Condense long conversation context
condensed = await llmService.condenseContext(
    messages,
    model=llmModel,
    keepFirstN=1,
    keepLastN=1,
    maxTokens=maxTokens,
    condensingModel=condensingModel,
    condensingPrompt=condensingPrompt,
)

# Register LLM tool
llmService.registerTool(
    name="search",
    function=LLMToolFunction(
        name="search",
        description="Search the web",
        parameters=[
            LLMFunctionParameter("query", "Search query", LLMParameterType.STRING, required=True)
        ],
    ),
    handler=mySearchHandler,  # async def mySearchHandler(**kwargs) -> str
)
```

**Generate structured (JSON-Schema) output:**
```python
result: ModelStructuredResult = await llmService.generateStructured(
    prompt,                      # Union[str, Sequence[ModelMessage]]
    schema,                      # Dict[str, Any] — JSON Schema
    chatId=chatId,
    chatSettings=chatSettings,
    llmManager=self.llmManager,
    modelKey=ChatSettingsKey.CHAT_MODEL,
    fallbackKey=ChatSettingsKey.CHAT_FALLBACK_MODEL,
    schemaName="response",       # optional; identifies schema to provider
    strict=True,                 # optional; request strict schema enforcement
    doDebugLogging=True,         # optional
)

if result.status == ModelResultStatus.FINAL:
    parsedDict = result.data     # Optional[Dict[str, Any]]
```

**`generateStructured` full signature:**
```python
async def generateStructured(
    self,
    prompt: Union[str, Sequence[ModelMessage]],
    schema: Dict[str, Any],
    *,
    chatId: Optional[int],
    chatSettings: ChatSettingsDict,
    llmManager: LLMManager,
    modelKey: Union[ChatSettingsKey, AbstractModel, None],
    fallbackKey: Union[ChatSettingsKey, AbstractModel, None],
    schemaName: str = "response",
    strict: bool = True,
    doDebugLogging: bool = True,
) -> ModelStructuredResult
```

`generateStructured` mirrors `generateText` end-to-end: it resolves
the primary and fallback models from `chatSettings`, applies rate
limiting for non-`None` `chatId`, then delegates to
`AbstractModel.generateStructuredWithFallBack`. Key differences:

- Raises `NotImplementedError` if **neither** the primary nor the
  fallback model has `support_structured_output = true` in its config.
- Auto-swaps primary↔fallback when only the fallback supports the
  capability, avoiding a guaranteed `NotImplementedError` on the
  primary call.
- No auto-injected JSON hint: callers should include a system message
  hinting at JSON output; this wrapper will not inject one.

**Import** `ModelStructuredResult` from `lib.ai`:
```python
from lib.ai import ModelStructuredResult
```

**`ModelResultStatus` values:**
- `FINAL` — successful response
- `ERROR` — LLM error
- `TIMEOUT` — request timed out
- `EMPTY` — empty response

**IMPORTANT:** `LLMService` has an `initialized` guard (singleton init runs once). Never check `initialized` directly in new code

---

## 4. StorageService

**File:** [`internal/services/storage/service.py:24`](../../internal/services/storage/service.py:24)  
**Import:** `from internal.services.storage import StorageService`

```python
storage = StorageService.getInstance()

# MUST inject config before use (done by HandlersManager)
storage.injectConfig(configManager)

# Store binary data
storage.store("my/key.png", imageBytes)

# Retrieve data
data: Optional[bytes] = storage.get("my/key.png")

# Check existence
exists: bool = storage.exists("my/key.png")

# Delete
storage.delete("my/key.png")

# List keys
keys: List[str] = storage.list(prefix="attachments/", limit=100)
```

**Backends:** `null` (no-op), `fs` (filesystem), `s3` (AWS S3/compatible)

**IMPORTANT:** `StorageService.injectConfig(configManager)` MUST be called before any storage operations. This is done automatically by `HandlersManager`

---

## 5. RateLimiterManager

**File:** [`lib/rate_limiter/manager.py:12`](../../lib/rate_limiter/manager.py:12)  
**Import:** `from lib.rate_limiter import RateLimiterManager`

```python
manager = RateLimiterManager.getInstance()

# Apply rate limit for a named queue
await manager.applyLimit("yandex-search")  # Blocks if over limit

# Get stats
stats = manager.getStats("yandex-search")
# Returns: {"requestsInWindow": N, "maxRequests": N, "utilizationPercent": N, ...}
```

**Config in TOML:**
```toml
[ratelimiter.ratelimiters.<name>]
type = "SlidingWindow"
[ratelimiter.ratelimiters.<name>.config]
windowSeconds = 5
maxRequests = 5

[ratelimiter.queues]
yandex-search = "<limiter-name>"
openweathermap = "<limiter-name>"
```

---

## 6. Service Singleton Pattern

All services use this pattern. When MODIFYING a service, preserve the singleton structure

```python
import threading
from typing import Optional


class MyService:
    """Singleton service"""

    _instance: Optional["MyService"] = None
    _lock: threading.RLock = threading.RLock()

    def __new__(cls) -> "MyService":
        """Create or return singleton instance

        Returns:
            The singleton MyService instance
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize service once"""
        if hasattr(self, "initialized"):
            return
        self.initialized: bool = True
        # ... actual init ...

    @classmethod
    def getInstance(cls) -> "MyService":
        """Get the singleton instance

        Returns:
            The singleton MyService instance
        """
        return cls()
```

**Rules for singletons:**
- Always use `getInstance()` — never `MyService()` directly
- Thread safety via `RLock`
- `hasattr(self, "initialized")` guard prevents double-init
- In tests, reset with `MyService._instance = None` (use autouse fixture)

---

## See Also

- [`index.md`](index.md) — Project overview, singleton services quick reference
- [`architecture.md`](architecture.md) — ADR-001 (singleton services), service initialization order
- [`handlers.md`](handlers.md) — Using services from handler methods
- [`database.md`](database.md) — CacheService for DB hot-path access
- [`libraries.md`](libraries.md) — Low-level lib/ai, lib/cache, lib/rate_limiter APIs
- [`configuration.md`](configuration.md) — Service TOML config sections
- [`testing.md`](testing.md) — Mocking services in tests, singleton reset fixtures

---

*This guide is auto-maintained and should be updated whenever service integration patterns change*  
*Last updated: 2026-05-06*
