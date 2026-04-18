# Simplification Suggestions for Gromozeka

> **Purpose:** Identify areas of unnecessary complexity, over-engineering, or indirection that make
> the codebase harder to understand and maintain, dood! This is NOT about restructuring — it's about
> *removing* complexity that doesn't earn its keep, dood!
>
> **Scope:** Based on analysis of the actual code in the repository as of 2026-04-18, dood.

---

## Summary Table

| # | Title | Priority | Effort | What Gets Simpler |
|---|-------|----------|--------|-------------------|
| 1 | [Eliminate `lib/cache/` — it duplicates `CacheService` for no gain](#1-eliminate-libcache--it-duplicates-cacheservice-for-no-gain) | High | S | Remove one entire sub-library |
| 2 | [Extract Singleton boilerplate into a reusable mixin](#2-extract-singleton-boilerplate-into-a-reusable-mixin) | Medium | S | ~60 identical lines across 3 classes |
| 3 | [Replace TheBot if/elif platform chains with a platform adapter](#3-replace-thebot-ifelif-platform-chains-with-a-platform-adapter) | High | M | 1000-line class → 2 focused adapters |
| 4 | [Remove the universal handler constructor signature repetition](#4-remove-the-universal-handler-constructor-signature-repetition) | Medium | S | 15+ identical `__init__` signatures |
| 5 | [Collapse ConfigManager get* one-liner wrappers](#5-collapse-configmanager-get-one-liner-wrappers) | Low | S | ~70 lines of mechanical boilerplate |
| 6 | [Fix LRUCache duplicate model storage in LLMManager](#6-fix-lrucache-duplicate-model-storage-in-llmmanager) | Medium | S | Models stored twice; confusing lookup |
| 7 | [Rename and consolidate `settings`/`cachedSettings` in CacheService](#7-rename-and-consolidate-settingscachedsettings-in-cacheservice) | High | S | Two overlapping concepts, confusing naming |
| 8 | [Remove deprecated mediaId/mediaContent fields from EnsuredMessage](#8-remove-deprecated-mediaidmediacontent-fields-from-ensuredmessage) | Medium | M | Dead code + TODO that nobody acts on |
| 9 | [Extract duplicated handler-chain loop into one helper](#9-extract-duplicated-handler-chain-loop-into-one-helper) | Medium | S | 4 copy-pasted for-loops in HandlersManager |
| 10 | [Replace polling in awaitStepDone with asyncio.Event](#10-replace-polling-in-awaitstepdone-with-asyncioevent) | Medium | S | Busy-wait polling → event-driven |
| 11 | [Merge double permission check in handleCommand](#11-merge-double-permission-check-in-handlecommand) | Medium | S | Two separate checks doing the same thing |
| 12 | [Simplify CacheInterface KeyGenerator strategy](#12-simplify-cacheinterface-keygenerator-strategy) | Medium | S | Unnecessary strategy pattern overhead |
| 13 | [Simplify RateLimiterManager for the common single-limiter case](#13-simplify-ratelimitermanager-for-the-common-single-limiter-case) | Low | S | Over-engineered queue-to-limiter mapping |
| 14 | [Fix post-construction dependency injection anti-pattern](#14-fix-post-construction-dependency-injection-anti-pattern) | High | L | `injectDatabase`/`injectBot`/`injectConfig` calls everywhere |
| 15 | [Simplify HCChatCacheDict string-key magic constants](#15-simplify-hcchatcachedict-string-key-magic-constants) | Medium | M | Scattered string literal keys like `"settings"`, `"info"` |
| 16 | [Replace asyncio.run() inside GromozekBot constructor](#16-replace-asynciorun-inside-gromozekbot-constructor) | High | S | Mixing sync/async setup dangerously |
| 17 | [Remove unused `forceRecalc` parameters](#17-remove-unused-forcrecalc-parameters) | Low | S | Parameters that are never passed as True |

---

## 1. Eliminate `lib/cache/` — it duplicates `CacheService` for no gain

**Priority:** High | **Effort:** S

### Current Complexity

There are **two completely separate caching systems** in the repo, dood:

- [`lib/cache/interface.py`](../lib/cache/interface.py:15) — Generic `CacheInterface[K, V]` with async `get`/`set`/`clear` and a pluggable `KeyGenerator[K]` strategy  
- [`lib/cache/dict_cache.py`](../lib/cache/dict_cache.py:41) — `DictCache[K, V]` implementing that interface  
- [`internal/services/cache/service.py`](../internal/services/cache/service.py:88) — `CacheService` with its own `LRUCache[K, V]` and all bot-specific cache methods

The `lib/cache/` system is used in exactly **one place** — inside `lib/yandex_search/cache_utils.py` — for Yandex Search result caching. The rest of the bot uses `CacheService` exclusively. So we have two implementations of the same concept, dood!

```python
# lib/cache/interface.py:15 — requires async and a KeyGenerator strategy just for str conversion
class CacheInterface(ABC, Generic[K, V]):
    @abstractmethod
    async def get(self, key: K, ttl: Optional[int] = None) -> Optional[V]: ...
    @abstractmethod
    async def set(self, key: K, value: V) -> bool: ...

# lib/cache/dict_cache.py:60 — requires a separate KeyGenerator object
def __init__(self, keyGenerator: KeyGenerator[K], defaultTtl: int = 3600, maxSize: Optional[int] = 1000)

# internal/services/cache/service.py:39 — completely separate implementation
class LRUCache[K, V](OrderedDict[K, V]):
    def get(self, key: K, default: V) -> V: ...
    def set(self, key: K, value: V) -> None: ...
```

### Proposed Simplification

Replace `lib/cache/DictCache` usage in `lib/yandex_search/cache_utils.py` with a simple `dict` + TTL check (5 lines of code), and delete `lib/cache/` entirely. Or, if a reusable cache is needed elsewhere, make `CacheService.LRUCache` importable as `lib.cache.LRUCache` — single implementation, dood!

```python
# Replacement for lib/yandex_search/cache_utils.py — no extra library needed
_cache: dict[str, tuple[Any, float]] = {}

def cacheGet(key: str, ttl: int) -> Optional[Any]:
    if key in _cache:
        val, ts = _cache[key]
        if time.time() - ts < ttl:
            return val
        del _cache[key]
    return None
```

### What Gets Simpler

- Delete `lib/cache/` directory (5 files, ~400 lines)
- Remove `KeyGenerator` strategy class — Python's `dict` accepts any hashable key
- Remove `CacheInterface` ABC — one less abstract concept to learn
- One caching pattern instead of two

### Trade-offs

None significant. `lib/cache/DictCache` adds async methods on a synchronous dict — `await cache.set(k, v)` is strictly worse than `cache[k] = v`, dood.

### Affected Files

- `lib/cache/interface.py`, `lib/cache/dict_cache.py`, `lib/cache/key_generator.py`, `lib/cache/types.py`, `lib/cache/__init__.py`
- `lib/yandex_search/cache_utils.py`

---

## 2. Extract Singleton boilerplate into a reusable mixin

**Priority:** Medium | **Effort:** S

### Current Complexity

Three services repeat **identical singleton code** (58+ lines total), dood:

```python
# internal/services/cache/service.py:105-127 (CacheService)
_instance: Optional["CacheService"] = None
_lock = RLock()

def __new__(cls) -> "CacheService":
    with cls._lock:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

def __init__(self):
    if not hasattr(self, "initialized"):
        # ... init code ...
        self.initialized = True

@classmethod
def getInstance(cls) -> "CacheService":
    return cls()
```

The same pattern exists verbatim in:
- [`internal/services/queue_service/service.py`](../internal/services/queue_service/service.py:82) — `QueueService`
- [`lib/rate_limiter/manager.py`](../lib/rate_limiter/manager.py:65) — `RateLimiterManager`

### Proposed Simplification

```python
# lib/singleton.py — define ONCE
from threading import RLock
from typing import TypeVar, Type

T = TypeVar("T", bound="Singleton")

class Singleton:
    """Thread-safe singleton mixin, dood!"""
    _instance = None
    _lock = RLock()

    def __new__(cls: Type[T]) -> T:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def getInstance(cls: Type[T]) -> T:
        return cls()
```

Then each service is simply:

```python
class CacheService(Singleton):
    def __init__(self):
        if not hasattr(self, "initialized"):
            self._setup()
            self.initialized = True
```

### What Gets Simpler

- ~55 lines deleted across 3 files
- One canonical place to understand the singleton pattern
- Easier testing (can mock `Singleton._instance`)

### Trade-offs

Minor: need to ensure `__new__` overrides still work correctly with inheritance.

### Affected Files

- New: `lib/singleton.py`
- `internal/services/cache/service.py`, `internal/services/queue_service/service.py`, `lib/rate_limiter/manager.py`

---

## 3. Replace TheBot if/elif platform chains with a platform adapter

**Priority:** High | **Effort:** M

### Current Complexity

[`internal/bot/common/bot.py`](../internal/bot/common/bot.py) is a 1000-line class where **every single method** contains a platform `if/elif` branch, dood:

```python
# internal/bot/common/bot.py:116-121
async def getBotId(self) -> int:
    if self.tgBot:
        return self.tgBot.id
    elif self.maxBot:
        return (await self.maxBot.getMyInfo()).user_id
    raise RuntimeError("No Active bot found")

# internal/bot/common/bot.py:150-191 — same pattern repeated for getChatAdmins
if self.botProvider == BotProvider.TELEGRAM and self.tgBot is not None:
    for admin in await self.tgBot.get_chat_administrators(chat_id=chat.id):
        ...
elif self.botProvider == BotProvider.MAX and self.maxBot is not None:
    maxChatAdmins = (await self.maxBot.getAdmins(chatId=chat.id)).members
    ...
else:
    raise RuntimeError(f"Unexpected platform: {self.botProvider}")
```

This pattern repeats for every operation: `getBotId`, `getBotUserName`, `getChatAdmins`, `isAdmin`, `sendMessage`, `sendMedia`, `deleteMessage`, and many more.

### Proposed Simplification

Extract the platform-specific code into two adapter classes and make `TheBot` delegate to the adapter, dood:

```python
# lib/bot_adapter/telegram_adapter.py
class TelegramBotAdapter:
    def __init__(self, tgBot: ExtBot): self._bot = tgBot
    async def getBotId(self) -> int: return self._bot.id
    async def getChatAdmins(self, chatId: int) -> Dict[int, Tuple[str, str]]:
        admins = {}
        for admin in await self._bot.get_chat_administrators(chat_id=chatId):
            ...
        return admins

# internal/bot/common/bot.py — simplified
class TheBot:
    def __init__(self, adapter: BotAdapterInterface, config: Dict[str, Any]):
        self._adapter = adapter
        ...
    async def getChatAdmins(self, chat: MessageRecipient):
        admins = self.cache.getChatAdmins(chat.id)
        if admins is not None:
            return admins
        admins = await self._adapter.getChatAdmins(chat.id)
        self.cache.setChatAdmins(chat.id, admins)
        return admins
```

### What Gets Simpler

- `TheBot` shrinks significantly (no more duplicated branches)
- Each platform's specifics live in one file
- Adding a third platform doesn't require touching `TheBot` at all
- `if self.tgBot: ... elif self.maxBot: ...` pattern eliminated everywhere

### Trade-offs

Medium refactoring effort — need to define the adapter interface and create two concrete implementations. But this is a natural decomposition that already exists conceptually, dood.

### Affected Files

- `internal/bot/common/bot.py` (major change)
- New: `internal/bot/adapters/telegram_adapter.py`, `internal/bot/adapters/max_adapter.py`, `internal/bot/adapters/interface.py`
- `internal/bot/common/handlers/manager.py` (injectBot method)

---

## 4. Remove the universal handler constructor signature repetition

**Priority:** Medium | **Effort:** S

### Current Complexity

Every single handler class has the **exact same constructor signature** with the same 4 arguments passed down unchanged to `super().__init__()`, dood:

```python
# internal/bot/common/handlers/llm_messages.py:75-86
def __init__(
    self, configManager: ConfigManager, database: DatabaseWrapper,
    llmManager: LLMManager, botProvider: BotProvider
):
    super().__init__(configManager=configManager, database=database,
                     llmManager=llmManager, botProvider=botProvider)

# Same in configure.py:71, media.py, spam.py, user_data.py, weather.py ...
# 15+ handlers all with identical signatures, dood!
```

And in [`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py:249-318), each handler is constructed with the same 4 arguments:
```python
(MessagePreprocessorHandler(configManager, database, llmManager, botProvider), ...),
(SpamHandler(configManager, database, llmManager, botProvider), ...),
(ConfigureCommandHandler(configManager, database, llmManager, botProvider), ...),
```

### Proposed Simplification

Group the 4 dependencies into a `HandlerContext` dataclass:

```python
# internal/bot/common/handlers/context.py
@dataclass
class HandlerContext:
    configManager: ConfigManager
    database: DatabaseWrapper
    llmManager: LLMManager
    botProvider: BotProvider
```

Then:
```python
# BaseBotHandler takes one argument
class BaseBotHandler(CommandHandlerMixin):
    def __init__(self, ctx: HandlerContext): ...

# All subclass constructors just call super (or disappear entirely)
class SpamHandler(BaseBotHandler):
    pass  # No custom __init__ needed, dood!

# HandlersManager constructs handlers cleanly
ctx = HandlerContext(configManager, database, llmManager, botProvider)
self.handlers = [
    (MessagePreprocessorHandler(ctx), HandlerParallelism.SEQUENTIAL),
    (SpamHandler(ctx), HandlerParallelism.SEQUENTIAL),
    ...
]
```

### What Gets Simpler

- ~60 lines of identical constructor code deleted
- Adding a new dependency to handlers requires changing one place (`HandlerContext`)
- Handler classes with no special init logic disappear entirely

### Trade-offs

Minor: all call sites need updating. If a handler needs additional deps (like `HelpHandler` which also takes `self`), they still add their own constructor but only for the extra param.

### Affected Files

- New: `internal/bot/common/handlers/context.py`
- `internal/bot/common/handlers/base.py` and all 15+ handler files
- `internal/bot/common/handlers/manager.py`

---

## 5. Collapse ConfigManager get* one-liner wrappers

**Priority:** Low | **Effort:** S

### Current Complexity

[`internal/config/manager.py`](../internal/config/manager.py:184-280) has many **identical one-liner wrapper methods** that only differ in the config key they access, dood:

```python
# internal/config/manager.py:184-233
def getBotConfig(self) -> Dict[str, Any]:
    return self.get("bot", {})

def getDatabaseConfig(self) -> Dict[str, Any]:
    return self.get("database", {})

def getLoggingConfig(self) -> Dict[str, Any]:
    return self.get("logging", {})

def getRateLimiterConfig(self) -> RateLimiterManagerConfig:
    return self.get("ratelimiter", {})

def getGeocodeMapsConfig(self) -> Dict[str, Any]:
    return self.get("geocode-maps", {})

def getModelsConfig(self) -> Dict[str, Any]:
    return self.get("models", {})

def getOpenWeatherMapConfig(self) -> Dict[str, Any]:
    return self.get("openweathermap", {})

def getYandexSearchConfig(self) -> Dict[str, Any]:
    return self.get("yandex-search", {})

def getStorageConfig(self) -> Dict[str, Any]:
    return self.get("storage", {})
```

The docstring for `getStorageConfig` is also hugely verbose (50 lines!) for what is `return self.get("storage", {})`, dood.

### Proposed Simplification

Either:
1. **Remove the wrappers entirely** — call sites use `configManager.get("bot", {})` directly (saves ~70 lines, minor readability cost)
2. **Or** keep them but auto-generate via a class-level mapping:

```python
# Define once, all wrappers generated automatically
_CONFIG_SECTIONS: dict[str, str] = {
    "getBotConfig": "bot",
    "getDatabaseConfig": "database",
    "getLoggingConfig": "logging",
    ...
}
```

### What Gets Simpler

- ~70 lines of mechanical code → 10 lines
- No need to read `getStorageConfig()` docstring to understand it returns `self.get("storage", {})`
- New section = one dict entry, not a new method

### Trade-offs

Callers lose IDE type hint completions for the specific method names. Minor. `self.get("bot", {})` is just as clear, dood.

### Affected Files

- `internal/config/manager.py`
- All files calling `configManager.getBotConfig()`, etc. (if wrappers removed)

---

## 6. Fix LRUCache duplicate model storage in LLMManager

**Priority:** Medium | **Effort:** S

### Current Complexity

Models are stored in **two separate dictionaries**, dood:

```python
# lib/ai/abstract.py:267 — AbstractLLMProvider stores models internally
class AbstractLLMProvider(ABC):
    def __init__(self, config: Dict[str, Any]):
        self.models: Dict[str, AbstractModel] = {}  # name -> model

# lib/ai/manager.py:27-28 — LLMManager ALSO stores a registry
class LLMManager:
    def __init__(self, config: Dict[str, Any]):
        self.providers: Dict[str, AbstractLLMProvider] = {}
        self.modelRegistry: Dict[str, str] = {}  # model_name -> provider_name
```

To get a model, two lookups are needed:
```python
# lib/ai/manager.py:122-130
def getModel(self, name: str) -> Optional[AbstractModel]:
    providerName = self.modelRegistry.get(name)      # lookup 1: model -> provider
    if not providerName:
        return None
    provider = self.providers.get(providerName)
    if not provider:
        return None
    return provider.getModel(name)                   # lookup 2: model from provider
```

### Proposed Simplification

Remove `modelRegistry` from `LLMManager`. Store models directly in a flat `modelMap`:

```python
class LLMManager:
    def __init__(self, config: Dict[str, Any]):
        self.providers: Dict[str, AbstractLLMProvider] = {}
        self._models: Dict[str, AbstractModel] = {}  # flat model_name -> model

    def getModel(self, name: str) -> Optional[AbstractModel]:
        return self._models.get(name)  # one lookup, dood!
```

Or equivalently, remove `provider.models` and keep only `LLMManager.modelRegistry` — either way, one dict suffices, dood.

### What Gets Simpler

- One lookup instead of two
- One dict to maintain instead of two
- `AbstractLLMProvider.models` becomes redundant (simplifies `AbstractLLMProvider` too)

### Trade-offs

`listModels()` for a specific provider needs a scan, but this is rarely called in hot paths.

### Affected Files

- `lib/ai/manager.py`
- `lib/ai/abstract.py`
- `lib/ai/providers/*.py` (all providers)

---

## 7. Rename and consolidate `settings`/`cachedSettings` in CacheService

**Priority:** High | **Effort:** S

### Current Complexity

[`internal/services/cache/service.py`](../internal/services/cache/service.py:203-368) has **two overlapping chat settings concepts** with very similar names, dood:

```python
# "settings" = raw settings loaded from DB (written by setChatSetting/setChatSettings)
chatCache["settings"] = {ChatSettingsKey.X: ChatSettingsValue(...), ...}

# "cachedSettings" = the MERGED settings (with defaults applied) cached from BaseBotHandler.getChatSettings()
chatCache["cachedSettings"] = {ChatSettingsKey.X: ChatSettingsValue(...), ...}
```

This causes:
- Developers don't know which one to use
- `getChatSettings()` loads from `"settings"`, `getCachedChatSettings()` loads from `"cachedSettings"` — same method name prefix, opposite semantics
- `clearCachedChatSettings()` only clears `"cachedSettings"` but leaves `"settings"` intact
- 4 separate methods handle two overlapping concepts: `getChatSettings`, `setChatSetting`, `getCachedChatSettings`, `cacheChatSettings`, `clearCachedChatSettings`

### Proposed Simplification

Rename clearly:
- `"settings"` → `"rawSettings"` (settings stored in DB, per-chat)
- `"cachedSettings"` → `"mergedSettings"` (computed defaults + per-chat settings)

And add a single invalidation method `invalidateMergedSettings(chatId)` instead of the current `clearCachedChatSettings`, dood.

### What Gets Simpler

- Anyone reading the code immediately understands the difference
- No more "why are there two settings keys?" confusion
- `getCachedChatSettings` and `getChatSettings` distinction becomes obvious

### Trade-offs

Requires updating string literals in CacheService and the TypedDict in `types.py`. Low risk, dood.

### Affected Files

- `internal/services/cache/service.py`
- `internal/services/cache/types.py` (`HCChatCacheDict`)
- `internal/bot/common/handlers/base.py` (calls `getCachedChatSettings`)

---

## 8. Remove deprecated mediaId/mediaContent fields from EnsuredMessage

**Priority:** Medium | **Effort:** M

### Current Complexity

[`internal/bot/models/ensured_message.py`](../internal/bot/models/ensured_message.py:449-456) has deprecated fields that are explicitly marked with a TODO but never cleaned up, dood:

```python
# internal/bot/models/ensured_message.py:449-456
# TODO: should we deprecate it in favor of mediaList?
self.mediaContent: Optional[str] = None
self.mediaPrompt: Optional[str] = None
self.mediaId: Optional[str] = None
```

The `__slots__` tuple (lines 358-383) contains `mediaContent`, `mediaPrompt`, `mediaId` alongside the newer `mediaList`. The code in `updateMediaContent()` updates both old and new fields:

```python
# internal/bot/models/ensured_message.py:969-975 — double writes
self.mediaContent = mediaAttachment["description"]
self.mediaPrompt = mediaAttachment["prompt"]
# AND ALSO updates media.content for each item in self.mediaList
```

### Proposed Simplification

Remove `mediaId`, `mediaContent`, `mediaPrompt` and all code that reads/writes them. Access media through `self.mediaList[0]` (with a guard), dood:

```python
@property
def primaryMedia(self) -> Optional[MediaContent]:
    return self.mediaList[0] if self.mediaList else None
```

This is a clean replacement for all `self.mediaContent` usages.

### What Gets Simpler

- 3 redundant fields removed from `__slots__`
- No more double-write logic in `updateMediaContent()`
- Clear API: `mediaList` for all media access
- ~40 lines of dead/duplicate code removed

### Trade-offs

Requires scanning all usages of `mediaId`, `mediaContent`, `mediaPrompt` and replacing them. Mostly mechanical, dood.

### Affected Files

- `internal/bot/models/ensured_message.py`
- `internal/bot/common/handlers/base.py` (media handling)
- `internal/bot/common/handlers/media.py`
- `internal/bot/common/handlers/llm_messages.py`

---

## 9. Extract duplicated handler-chain loop into one helper

**Priority:** Medium | **Effort:** S

### Current Complexity

[`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py:774-891) has **4 near-identical for-loops** that iterate through handlers and check `isFinalState()`, dood:

```python
# manager.py:774 — _handleCallback
for handler, _ in self.handlers:
    ret = await handler.callbackHandler(...)
    retSet.add(ret)
    if ret.needLogs():
        logger.debug(f"Handler {type(handler).__name__} returned {ret.value}")
    if ret.isFinalState():
        break

# manager.py:824 — _handleNewChatMember (same loop)
for handler, _ in self.handlers:
    ret = await handler.newChatMemberHandler(...)
    retSet.add(ret)
    if ret.needLogs():
        logger.debug(f"Handler {type(handler).__name__} returned {ret.value}")
    if ret.isFinalState():
        break

# manager.py:877 — _handleLeftChatMember (same loop again)
# manager.py:709 — _processMessageRec (more complex variant)
```

### Proposed Simplification

```python
async def _runHandlerChain(
    self,
    handlerMethod: str,
    **kwargs: Any,
) -> Set[HandlerResultStatus]:
    """Run all handlers for the given event method name, stopping on final state, dood!"""
    retSet: Set[HandlerResultStatus] = set()
    for handler, _ in self.handlers:
        ret: HandlerResultStatus = await getattr(handler, handlerMethod)(**kwargs)
        retSet.add(ret)
        if ret.needLogs():
            logger.debug(f"Handler {type(handler).__name__} returned {ret.value}")
        if ret.isFinalState():
            break
    return retSet

# Then usage becomes:
async def _handleCallback(self, ensuredMessage, data, user, updateObj):
    retSet = await self._runHandlerChain(
        "callbackHandler",
        ensuredMessage=ensuredMessage, data=data, user=user, updateObj=updateObj
    )
    logger.debug(f"Handled CallbackQuery, resultsSet: {retSet}")
```

### What Gets Simpler

- ~50 lines of duplicate code removed
- Event handling pattern is now obvious and consistent
- Adding new event types is trivial

### Trade-offs

Using `getattr(handler, handlerMethod)` loses static type checking. Alternatively, pass a `Callable` — still much cleaner than 4 copy-pasted loops, dood.

### Affected Files

- `internal/bot/common/handlers/manager.py`

---

## 10. Replace polling in awaitStepDone with asyncio.Event

**Priority:** Medium | **Effort:** S

### Current Complexity

[`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py:110-113) uses **busy polling** with `asyncio.sleep(0.1)` to wait for steps, dood:

```python
# manager.py:110-113
async def awaitStepDone(self, step: int) -> None:
    while not self.handled.is_set() and self.step < step:
        await asyncio.sleep(0.1)  # polling every 100ms, dood!
```

Similarly in `messageProcessed`:
```python
# manager.py:155-157
while self.queue and self.queue[0].getId() != messageId:
    # Wait for previous messages to be processed and removed
    await asyncio.sleep(0.1)  # more polling!
```

### Proposed Simplification

Use proper `asyncio.Event` per step:

```python
class MessageQueueRecord:
    def __init__(self, message, updateObj, stateId=None):
        self._stepEvents: Dict[int, asyncio.Event] = {}
        ...

    def markStepDone(self, step: int) -> None:
        event = self._stepEvents.setdefault(step, asyncio.Event())
        event.set()

    async def awaitStepDone(self, step: int) -> None:
        if self.handled.is_set() or self.step >= step:
            return
        event = self._stepEvents.setdefault(step, asyncio.Event())
        await event.wait()  # no polling, truly event-driven, dood!
```

### What Gets Simpler

- True event-driven code instead of 100ms polling
- Lower CPU usage under load
- More predictable latency (no 0-100ms random delay per step)

### Trade-offs

Slightly more memory per message record (one `Event` per step). Negligible in practice, dood.

### Affected Files

- `internal/bot/common/handlers/manager.py`

---

## 11. Merge double permission check in handleCommand

**Priority:** Medium | **Effort:** S

### Current Complexity

[`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py:566-629) runs **two separate permission checks** for each command, with the same error/delete-message logic duplicated, dood:

```python
# Check 1: CommandPermission enum check (lines 571-594)
canProcess = (
    CommandPermission.DEFAULT in handlerInfo.availableFor
    or (CommandPermission.PRIVATE in handlerInfo.availableFor and chatType == ChatType.PRIVATE)
    or (CommandPermission.GROUP in handlerInfo.availableFor and chatType == ChatType.GROUP)
    or ...
)
if not canProcess:
    # delete message, log, return False

# Check 2: CommandCategory check (lines 597-629)
match handlerInfo.category:
    case CommandCategory.ADMIN | CommandCategory.SPAM_ADMIN:
        canProcess = isAdmin
    case CommandCategory.TOOLS:
        canProcess = chatSettings[ChatSettingsKey.ALLOW_TOOLS_COMMANDS].toBool() or isBotOwner
    ...
if not canProcess:
    # delete message, log, return False  (same code as above!)
```

The delete-message/log/return block is identical in both check failures.

### Proposed Simplification

Merge into a single permission evaluation function and one response block:

```python
async def _checkCommandPermissions(self, handlerInfo, ensuredMessage, chatSettings) -> bool:
    """Return True if the command is allowed, dood!"""
    chatType = ensuredMessage.recipient.chatType
    isBotOwner = await handlerObj.isAdmin(ensuredMessage.sender, None, allowBotOwners=True)
    isAdmin = await handlerObj.isAdmin(ensuredMessage.sender, ensuredMessage.recipient)

    # Check CommandPermission (who can see the command at all)
    if not _checkCommandPermission(handlerInfo.availableFor, chatType, isBotOwner, isAdmin):
        return False

    # Check CommandCategory (context where it can run)
    return _checkCommandCategory(handlerInfo.category, chatType, isBotOwner, isAdmin, chatSettings)
```

### What Gets Simpler

- ~30 lines of duplicated error handling removed
- Permission logic is readable in one place
- `isAdmin` called once instead of potentially twice

### Trade-offs

None. Pure simplification, dood.

### Affected Files

- `internal/bot/common/handlers/manager.py`

---

## 12. Simplify CacheInterface KeyGenerator strategy

**Priority:** Medium | **Effort:** S

### Current Complexity

[`lib/cache/dict_cache.py`](../lib/cache/dict_cache.py:60-65) requires a separate `KeyGenerator[K]` strategy object just to convert keys to strings for internal dict storage, dood:

```python
class DictCache(CacheInterface[K, V]):
    def __init__(
        self,
        keyGenerator: KeyGenerator[K],   # <- why?
        defaultTtl: int = 3600,
        maxSize: Optional[int] = 1000,
    ):
```

The `KeyGenerator` interface exists to abstract "how to turn a K into a string", but Python's built-in `dict` can use any hashable key directly without conversion to string. The only `KeyGenerator` implementation is `StringKeyGenerator` which just calls `str(key)`, dood.

### Proposed Simplification

Remove `KeyGenerator` entirely. Use the key directly in `self._cache: Dict[K, Tuple[V, float]]`:

```python
class DictCache(CacheInterface[K, V]):
    def __init__(self, defaultTtl: int = 3600, maxSize: Optional[int] = 1000):
        self._cache: Dict[K, Tuple[V, float]] = {}
        ...

    async def get(self, key: K, ttl: Optional[int] = None) -> Optional[V]:
        if key in self._cache:
            value, timestamp = self._cache[key]
            ...
```

### What Gets Simpler

- Delete `lib/cache/key_generator.py` (30+ lines)
- Remove `keyGenerator` parameter from `DictCache.__init__`
- All call sites simpler: `DictCache[str, dict](ttl=3600)` instead of `DictCache[str, dict](StringKeyGenerator(), 3600)`

### Trade-offs

If custom key serialization is ever needed (e.g., tuple key → composite string), this can be done inline. The `KeyGenerator` abstraction provides no real value here, dood.

### Affected Files

- `lib/cache/key_generator.py` (delete)
- `lib/cache/dict_cache.py`
- `lib/cache/interface.py` (remove Generic type parameter)
- `lib/yandex_search/cache_utils.py`

---

## 13. Simplify RateLimiterManager for the common single-limiter case

**Priority:** Low | **Effort:** S

### Current Complexity

[`lib/rate_limiter/manager.py`](../lib/rate_limiter/manager.py) implements a full **queue-to-limiter mapping** system with named limiters, `bindQueue()`, `setDefaultLimiter()`, etc. But looking at the actual config in [`configs/00-defaults/00-config.toml`](../configs/00-defaults/00-config.toml:29-44):

```toml
[ratelimiter.ratelimiters.default]
type = "SlidingWindow"
[ratelimiter.ratelimiters.default.config]
windowSeconds = 5
maxRequests = 5

[ratelimiter.ratelimiters.one-per-second]
type = "SlidingWindow"
windowSeconds = 1
maxRequests = 1

[ratelimiter.queues]
yandex-search = "default"
openweathermap = "default"
geocode-maps = "one-per-second"
```

There are only **2 limiters** and all queues use one of them. The manager exposes: `registerRateLimiter`, `setDefaultLimiter`, `bindQueue`, `_getLimiterForQueue`, `applyLimit`, `getStats`, `listRateLimiters`, `getQueueMappings`, `getDefaultLimiter`, `destroy` — 10 methods for essentially a two-entry dict.

### Proposed Simplification

A simple dict of per-queue limiters with a fallback default covers 100% of actual usage:

```python
class RateLimiterManager(Singleton):
    async def applyLimit(self, queue: str) -> None:
        limiter = self._limiters.get(queue) or self._default
        await limiter.applyLimit(queue)
```

Or, even simpler — just expose `applyLimit(queue, config)` and let callers own the config, removing the need for a manager singleton at all for most cases, dood.

### What Gets Simpler

- Manager goes from 350 to ~80 lines
- Fewer concepts: no "register", "bind", "setDefault" ceremony
- The config is already expressive enough; the manager is just a lookup

### Trade-offs

Less flexible for future cases with many different limiters, but YAGNI applies here, dood.

### Affected Files

- `lib/rate_limiter/manager.py`
- `main.py` (simpler initialization)

---

## 14. Fix post-construction dependency injection anti-pattern

**Priority:** High | **Effort:** L

### Current Complexity

Multiple singletons can't receive their dependencies in the constructor because they're singletons. So dependencies are injected after construction via special methods, dood:

```python
# internal/bot/common/handlers/manager.py:205-209
self.cache = CacheService.getInstance()
self.cache.injectDatabase(self.db)     # ← post-construction!

self.storage = StorageService.getInstance()
self.storage.injectConfig(self.configManager)  # ← post-construction!
```

And in [`internal/services/cache/service.py`](../internal/services/cache/service.py:185-190):
```python
def injectDatabase(self, dbWrapper: "DatabaseWrapper") -> None:
    """Inject database wrapper for persistence"""
    self.dbWrapper = dbWrapper
    self.loadFromDatabase()  # ← side effect on injection!
```

This means services have an implicit "initialization phase 2" that must be called before they work correctly. If you forget to call `injectDatabase`, you get silent errors (`if self.dbWrapper:` guards everywhere).

### Proposed Simplification

Pass dependencies at construction time. Since singletons must be created before all deps are available, one solution is lazy initialization via a `setup()` method that's called once and asserts it hasn't been called before:

```python
class CacheService(Singleton):
    def setup(self, dbWrapper: DatabaseWrapper) -> None:
        if hasattr(self, "_setup_done"):
            raise RuntimeError("CacheService.setup() called twice, dood!")
        self.dbWrapper = dbWrapper
        self.loadFromDatabase()
        self._setup_done = True

    def _requireDb(self) -> DatabaseWrapper:
        if self.dbWrapper is None:
            raise RuntimeError("CacheService not set up yet, call setup() first, dood!")
        return self.dbWrapper
```

Then replace `if self.dbWrapper: ... else: logger.error(...)` guards with `self._requireDb()` — fail fast, not silently, dood.

### What Gets Simpler

- Initialization order is explicit and enforced
- Silent `if self.dbWrapper:` guards replaced with clear errors
- ~30 error log messages that say "can't save X because no dbWrapper" disappear
- The code becomes self-documenting: "setup() must be called before first use"

### Trade-offs

Significant change — all `injectDatabase`, `injectConfig`, `injectBot` patterns need updating across the codebase. But the resulting code is more correct and easier to reason about, dood.

### Affected Files

- `internal/services/cache/service.py`
- `internal/services/queue_service/service.py`
- `internal/services/storage/service.py`
- `internal/bot/common/handlers/manager.py`
- `internal/bot/common/handlers/base.py`

---

## 15. Simplify HCChatCacheDict string-key magic constants

**Priority:** Medium | **Effort:** M

### Current Complexity

[`internal/services/cache/types.py`](../internal/services/cache/types.py:41-48) defines `HCChatCacheDict` as a `TypedDict` with the keys `"settings"`, `"cachedSettings"`, `"info"`, `"topicInfo"`, `"admins"`. But throughout [`CacheService`](../internal/services/cache/service.py) these are accessed via **magic string literals** scattered everywhere, dood:

```python
# internal/services/cache/service.py:253
chatCache = self.chats.get(chatId, {})
if "settings" not in chatCache:    # string literal

# service.py:336
cachedSettings = chatCache.get("cachedSettings", None)  # string literal

# service.py:374-376
info = chatCache.get("info", None)  # string literal

# service.py:410-412
if "topicInfo" not in chatCache:   # string literal
```

The `TypedDict` should prevent this, but because `LRUCache.get()` returns the entire dict and then we manually access sub-keys with strings, the type system doesn't help here.

### Proposed Simplification

Replace magic strings with an `Enum` of cache field names, and create typed accessor helpers:

```python
class ChatCacheField(StrEnum):
    SETTINGS = "settings"
    CACHED_SETTINGS = "cachedSettings"
    INFO = "info"
    TOPIC_INFO = "topicInfo"
    ADMINS = "admins"

# Or better yet: split HCChatCacheDict into separate typed namespaces
# (one LRUCache for settings, one for info, one for admins)
# so each is accessed with type-safe methods, not dict strings
```

### What Gets Simpler

- No magic strings scattered throughout CacheService
- Typo in a key name is caught at definition time, not runtime
- IDE autocomplete works for cache field access

### Trade-offs

Medium refactor effort. Splitting into multiple namespaces requires more LRUCache instances but gains full type safety, dood.

### Affected Files

- `internal/services/cache/service.py` (heavy)
- `internal/services/cache/types.py`

---

## 16. Replace asyncio.run() inside GromozekBot constructor

**Priority:** High | **Effort:** S

### Current Complexity

[`main.py`](../main.py:50) calls `asyncio.run()` **inside a class constructor**, which is an async/sync mixing anti-pattern, dood:

```python
# main.py:46-51
class GromozekBot:
    def __init__(self, configManager: ConfigManager):
        ...
        self.rateLimiterManager = RateLimiterManager.getInstance()
        asyncio.run(self.rateLimiterManager.loadConfig(  # ← asyncio.run() in constructor!
            self.configManager.getRateLimiterConfig()
        ))
```

`asyncio.run()` creates and destroys a **new event loop** just for this one config load. This means:
- Creates/destroys an event loop during synchronous initialization
- Will fail if an event loop is already running (e.g., if anyone ever makes `__init__` async-aware)
- Confusing to future readers: why is a constructor running an event loop?

### Proposed Simplification

Move async initialization into an `async setup()` method or into `run()`:

```python
class GromozekBot:
    def __init__(self, configManager: ConfigManager):
        self.configManager = configManager
        initLogging(configManager.getLoggingConfig())
        self.database_manager = DatabaseManager(configManager.getDatabaseConfig())
        self.llmManager = LLMManager(configManager.getModelsConfig())
        self.rateLimiterManager = RateLimiterManager.getInstance()
        # No asyncio.run() here, dood!

    async def setup(self) -> None:
        await self.rateLimiterManager.loadConfig(self.configManager.getRateLimiterConfig())
        # ... any other async setup

    def run(self):
        asyncio.run(self._runAsync())

    async def _runAsync(self) -> None:
        await self.setup()
        await self.botApp.runAsync()
```

### What Gets Simpler

- No `asyncio.run()` in a constructor
- Clear separation: sync init vs async setup
- Easy to test: `await bot.setup()` without wrapping in `asyncio.run()`

### Trade-offs

Minor: `main()` needs to call `bot.run()` which internally calls `asyncio.run()` — same end result but clean architecture, dood.

### Affected Files

- `main.py`
- `internal/bot/telegram/application.py`, `internal/bot/max/application.py` (run methods)

---

## 17. Remove unused `forceRecalc` parameters

**Priority:** Low | **Effort:** S

### Current Complexity

[`internal/bot/common/handlers/manager.py`](../internal/bot/common/handlers/manager.py:92-103) has parameters that are **never used**, dood:

```python
# manager.py:92-96
def getId(self, forceRecalc: bool = False) -> str:
    if self._id is None or forceRecalc:   # forceRecalc never passed as True
        self._id = f"{self.message.recipient.id}:{self.message.messageId}"
    return self._id

def getStateId(self, forceRecalc: bool = False) -> str:  # same pattern
    if self._stateId is None or forceRecalc:
        self._stateId = f"{self.message.recipient.id}:{self.message.threadId}"
    return self._stateId

# Same pattern in ChatProcessingState:
def getQueueKey(self, forceRecalc: bool = False) -> str:
    if self._queueKey is None or forceRecalc:
        ...
```

`forceRecalc` is never passed as `True` anywhere in the codebase — it's defensive programming that adds complexity without benefit, dood.

### Proposed Simplification

```python
def getId(self) -> str:
    if self._id is None:
        self._id = f"{self.message.recipient.id}:{self.message.messageId}"
    return self._id
```

Or even simpler — compute these in `__init__` since they never change:
```python
def __init__(self, message, updateObj, stateId=None):
    self._id = f"{message.recipient.id}:{message.messageId}"
    self._stateId = stateId or f"{message.recipient.id}:{message.threadId}"
```

### What Gets Simpler

- `forceRecalc` parameter removed (3 occurrences)
- The "lazy caching" becomes unnecessary (IDs are cheap to compute)
- ~15 lines simplified

### Trade-offs

None. The IDs are strings computed from already-available fields, dood.

### Affected Files

- `internal/bot/common/handlers/manager.py`

---

## Appendix: Quick Wins (can be done immediately, dood!)

These don't need a full section but are worth noting:

| Location | Issue | Fix |
|---|---|---|
| [`internal/bot/common/bot.py:75`](../internal/bot/common/bot.py:75) | Typo: `"tgBot need to be providen if botProvider is Telegram"` — says Telegram even for Max case | Fix the error message |
| [`internal/bot/common/handlers/manager.py:616`](../internal/bot/common/handlers/manager.py:616) | `canProcess = False; pass` — `pass` after `canProcess = False` is dead code | Remove `pass` |
| [`internal/bot/models/ensured_message.py:1111`](../internal/bot/models/ensured_message.py:1111) | `raise RuntimeError("Unreacible code has been reached")` after exhaustive match | Fix typo "Unreacible" + this IS reachable if `format` is some unknown value |
| [`lib/ai/manager.py:51-53`](../lib/ai/manager.py:51) | f-string without f prefix: `"Provider type is not specified for provider {provider_name}"` | Add `f` prefix |
| [`internal/bot/common/handlers/manager.py:447`](../internal/bot/common/handlers/manager.py:447) | `TODO: Write docstring` on `addMessageToChatQueue` | Write it or remove comment |

---

*Document created 2026-04-18, dood! Analysis based on codebase snapshot at that date.*
